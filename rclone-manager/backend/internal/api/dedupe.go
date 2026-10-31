package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"rclone-manager/internal/models"
)

const dedupeConfig = "/root/.config/rclone/rclone.conf"

// Dedupe intentionally has one in-memory job at a time. A restart discards a
// preview, so an old selection can never be applied to a changed remote.
var dedupeState = struct {
	sync.Mutex
	job dedupeJob
}{}

type dedupeFinding struct {
	ID           string               `json:"id"`
	Kind         string               `json:"kind"`
	ItemType     string               `json:"item_type,omitempty"`
	Path         string               `json:"path"`
	Scope        string               `json:"scope"`
	Count        int                  `json:"count"`
	Details      []string             `json:"details"`
	Contents     []dedupeCopyContents `json:"contents,omitempty"`
	ContentsNote string               `json:"contents_note,omitempty"`
	Result       string               `json:"result,omitempty"`
}

type dedupeJob struct {
	ID       string          `json:"id"`
	Remote   string          `json:"remote"`
	Path     string          `json:"path"`
	Status   string          `json:"status"`
	Started  time.Time       `json:"started_at"`
	Finished *time.Time      `json:"finished_at,omitempty"`
	Findings []dedupeFinding `json:"findings"`
	Error    string          `json:"error,omitempty"`
	Log      []string        `json:"log,omitempty"`
}

type cappedOutput struct {
	bytes.Buffer
	limit int
	cut   bool
}

func (b *cappedOutput) Write(p []byte) (int, error) {
	n := len(p)
	left := b.limit - b.Len()
	if left <= 0 {
		b.cut = true
		return n, nil
	}
	if len(p) > left {
		b.cut = true
		p = p[:left]
	}
	_, _ = b.Buffer.Write(p)
	return n, nil
}

func runDedupeRclone(ctx context.Context, limit int, args ...string) (string, error) {
	output := &cappedOutput{limit: limit}
	cmd := exec.CommandContext(ctx, "rclone", args...)
	cmd.Stdout = output
	cmd.Stderr = output
	err := cmd.Run()
	if output.cut {
		if err == nil && len(args) > 0 && (args[0] == "rmdir" || args[0] == "rmdirs" || (len(args) > 1 && args[0] == "dedupe" && (args[1] == "skip" || args[1] == "newest"))) {
			return output.String() + "\n…rclone 输出已截断；命令本身执行成功", nil
		}
		return "", errors.New("扫描结果过大，请缩小扫描目录后重试")
	}
	if err != nil {
		msg := strings.TrimSpace(output.String())
		if len(msg) > 500 {
			msg = msg[len(msg)-500:]
		}
		return "", fmt.Errorf("rclone 执行失败：%w；%s", err, msg)
	}
	return output.String(), nil
}

func validDedupeTarget(remote, rawPath string) (string, error) {
	remote = strings.TrimSpace(remote)
	if remote == "" || strings.ContainsAny(remote, ":/\\\r\n") {
		return "", errors.New("请选择有效的远端")
	}
	config, err := os.ReadFile(dedupeConfig)
	if err != nil {
		return "", fmt.Errorf("无法读取 rclone 配置：%w", err)
	}
	found := false
	for _, line := range strings.Split(string(config), "\n") {
		if strings.TrimSpace(line) == "["+remote+"]" {
			found = true
			break
		}
	}
	if !found {
		return "", errors.New("远端不在当前 rclone 配置中")
	}
	rawPath = strings.ReplaceAll(strings.TrimSpace(rawPath), "\\", "/")
	for _, part := range strings.Split(rawPath, "/") {
		if part == ".." {
			return "", errors.New("目录不能包含上级路径")
		}
	}
	if strings.ContainsAny(rawPath, ":\r\n") {
		return "", errors.New("目录包含无效字符")
	}
	return path.Clean("/" + strings.TrimPrefix(rawPath, "/")), nil
}

func dedupeRemotePath(remote, directory string) string {
	return remote + ":" + directory
}

func withinDedupeRoot(root, scope string) bool {
	root = path.Clean(root)
	scope = path.Clean(scope)
	return root == "/" || scope == root || strings.HasPrefix(scope, root+"/")
}

var (
	duplicateDirLine  = regexp.MustCompile(`^(.+): ([0-9]+) duplicates of this directory$`)
	duplicateFileLine = regexp.MustCompile(`^(.+): ([0-9]+) duplicates$`)
)

func parseDedupeList(output, root string) []dedupeFinding {
	groups := make(map[string]*dedupeFinding)
	var current *dedupeFinding
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimRight(line, "\r")
		kind := ""
		match := duplicateDirLine.FindStringSubmatch(line)
		if match != nil {
			kind = "同名目录"
		} else {
			match = duplicateFileLine.FindStringSubmatch(line)
			if match != nil {
				kind = "同名文件"
			}
		}
		if kind != "" {
			rel := strings.TrimPrefix(path.Clean("/"+match[1]), "/")
			full := path.Join(root, rel)
			scope := path.Dir(full)
			if !withinDedupeRoot(root, scope) {
				current = nil
				continue
			}
			if scope == "." {
				scope = root
			}
			group := groups[full]
			if group == nil {
				group = &dedupeFinding{ID: "merge:" + full, Kind: "merge", ItemType: kind, Path: full, Scope: scope, Details: []string{}}
				groups[full] = group
			}
			group.Count, _ = strconv.Atoi(match[2])
			group.Details = append(group.Details, fmt.Sprintf("%s：%s（%s 个副本）", kind, full, match[2]))
			current = group
			continue
		}
		if current != nil && strings.HasPrefix(line, "  ") && len(current.Details) > 0 {
			// Rclone prints sizes, timestamps and hashes below duplicate files.
			// Keep a bounded preview, never a full command log in API state.
			if len(current.Details) < 200 {
				current.Details = append(current.Details, strings.TrimSpace(line))
			}
		}
	}
	findings := make([]dedupeFinding, 0, len(groups))
	for _, group := range groups {
		findings = append(findings, *group)
	}
	sort.Slice(findings, func(i, j int) bool { return findings[i].Path < findings[j].Path })
	return findings
}

func emptyDedupeDirs(output, root string) ([]dedupeFinding, error) {
	var entries []rcloneJSONEntry
	if err := json.Unmarshal([]byte(output), &entries); err != nil {
		return nil, fmt.Errorf("无法解析空目录扫描结果：%w", err)
	}
	all := make(map[string][]rcloneJSONEntry)
	occupied := make(map[string]bool)
	for _, entry := range entries {
		rel := strings.Trim(strings.ReplaceAll(entry.Path, "\\", "/"), "/")
		if rel == "" {
			continue
		}
		if entry.IsDir {
			all[rel] = append(all[rel], entry)
		}
		if !entry.IsDir {
			for parent := path.Dir(rel); parent != "." && parent != "/"; parent = path.Dir(parent) {
				occupied[parent] = true
			}
		}
	}
	findings := []dedupeFinding{}
	for rel, copies := range all {
		if !occupied[rel] {
			full := path.Join(root, rel)
			if !withinDedupeRoot(root, full) {
				continue
			}
			findings = append(findings, dedupeFinding{ID: "empty:" + full, Kind: "empty", Path: full, Scope: full, Count: len(copies)})
		}
	}
	sort.Slice(findings, func(i, j int) bool { return findings[i].Path < findings[j].Path })
	return findings, nil
}

func startDedupeScan(c *gin.Context) {
	var req struct {
		Remote string `json:"remote"`
		Path   string `json:"path"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请选择远端和目录"})
		return
	}
	directory, err := validDedupeTarget(req.Remote, req.Path)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	dedupeState.Lock()
	if dedupeState.job.Status == "scanning" || dedupeState.job.Status == "applying" {
		dedupeState.Unlock()
		c.JSON(http.StatusConflict, gin.H{"error": "已有扫描或处理任务正在运行"})
		return
	}
	id := fmt.Sprintf("%d", time.Now().UnixNano())
	dedupeState.job = dedupeJob{ID: id, Remote: req.Remote, Path: directory, Status: "scanning", Started: time.Now(), Findings: []dedupeFinding{}}
	dedupeState.Unlock()
	go scanDedupe(id, req.Remote, directory)
	c.JSON(http.StatusAccepted, gin.H{"id": id, "status": "scanning"})
}

func scanDedupe(id, remote, directory string) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Hour)
	defer cancel()
	target := dedupeRemotePath(remote, directory)
	output, err := runDedupeRclone(ctx, 16<<20, "dedupe", "list", target, "--config", dedupeConfig, "--log-level", "ERROR")
	findings := []dedupeFinding{}
	if err == nil {
		findings = parseDedupeList(output, directory)
		listing, listErr := runDedupeRclone(ctx, 32<<20, "lsjson", target, "--recursive", "--config", dedupeConfig)
		if listErr == nil {
			var empty []dedupeFinding
			empty, listErr = emptyDedupeDirs(listing, directory)
			findings = append(findings, empty...)
		}
		if listErr != nil {
			// Duplicate preview remains usable even if the optional empty-dir scan fails.
			findings = append(findings, dedupeFinding{ID: "warning:empty", Kind: "warning", Path: directory, Details: []string{listErr.Error()}})
		}
	}
	dedupeState.Lock()
	defer dedupeState.Unlock()
	if dedupeState.job.ID != id {
		return
	}
	now := time.Now()
	dedupeState.job.Finished = &now
	if err != nil {
		dedupeState.job.Status = "failed"
		dedupeState.job.Error = err.Error()
	} else {
		dedupeState.job.Status = "ready"
		dedupeState.job.Findings = findings
	}
}

func getDedupeScan(c *gin.Context) {
	dedupeState.Lock()
	job := dedupeState.job
	job.Findings = append([]dedupeFinding(nil), dedupeState.job.Findings...)
	job.Log = append([]string(nil), dedupeState.job.Log...)
	dedupeState.Unlock()
	c.JSON(http.StatusOK, job)
}

func requireDedupeWriteToken(c *gin.Context) {
	requireTokenQuery(c)
}

func applyDedupeSelection(c *gin.Context) {
	var req struct {
		ID         string   `json:"id"`
		FindingIDs []string `json:"finding_ids"`
		Confirm    string   `json:"confirm_remote"`
	}
	if err := c.ShouldBindJSON(&req); err != nil || len(req.FindingIDs) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请先勾选要处理的项目"})
		return
	}
	dedupeState.Lock()
	job := dedupeState.job
	if job.ID == "" || job.ID != req.ID || job.Status != "ready" {
		dedupeState.Unlock()
		c.JSON(http.StatusConflict, gin.H{"error": "预览已过期或任务正在运行，请重新扫描"})
		return
	}
	if req.Confirm != job.Remote {
		dedupeState.Unlock()
		c.JSON(http.StatusBadRequest, gin.H{"error": "确认的远端与扫描结果不一致"})
		return
	}
	selected := map[string]bool{}
	for _, id := range req.FindingIDs {
		selected[id] = true
	}
	work := []dedupeFinding{}
	for _, finding := range job.Findings {
		if selected[finding.ID] && (finding.Kind == "merge" || finding.Kind == "empty") {
			work = append(work, finding)
			delete(selected, finding.ID)
		}
	}
	if len(work) == 0 || len(selected) > 0 {
		dedupeState.Unlock()
		c.JSON(http.StatusBadRequest, gin.H{"error": "选择项目与本次扫描结果不一致"})
		return
	}
	dedupeState.job.Status = "applying"
	dedupeState.job.Log = []string{}
	dedupeState.Unlock()
	go runDedupeApply(job.ID, job.Remote, work)
	c.JSON(http.StatusAccepted, gin.H{"id": job.ID, "status": "applying", "count": len(work)})
}

func runDedupeApply(id, remote string, work []dedupeFinding) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Hour)
	defer cancel()
	failed := false
	// Merge outer scopes first; remove nested empty folders from the leaves upward.
	sort.Slice(work, func(i, j int) bool {
		if work[i].Kind != work[j].Kind {
			return work[i].Kind == "merge"
		}
		if work[i].Kind == "empty" {
			return len(work[i].Scope) > len(work[j].Scope)
		}
		return len(work[i].Scope) < len(work[j].Scope)
	})
	for _, finding := range work {
		target := dedupeRemotePath(remote, finding.Scope)
		args := []string{"dedupe", "newest", target, "--config", dedupeConfig}
		task := models.DedupeTask{SourceType: "remote", Remote: remote}
		var err error
		if finding.Kind == "empty" {
			_, err = removeEmptyDedupeDirectories(ctx, task, finding)
		} else {
			var filters []string
			filters, err = dedupeItemFilters(finding)
			if err == nil {
				args = append(args, filters...)
				_, err = runDedupeRclone(ctx, 1<<20, append(append([]string{}, args...), "--dry-run")...)
				if err == nil {
					_, err = runDedupeRclone(ctx, 1<<20, args...)
				}
			}
		}
		message := finding.Path + "：处理完成"
		if err != nil {
			failed = true
			message = finding.Path + "：" + err.Error()
		}
		dedupeState.Lock()
		if dedupeState.job.ID == id {
			dedupeState.job.Log = append(dedupeState.job.Log, message)
			for i := range dedupeState.job.Findings {
				if dedupeState.job.Findings[i].ID == finding.ID {
					dedupeState.job.Findings[i].Result = message
				}
			}
		}
		dedupeState.Unlock()
	}
	dedupeState.Lock()
	defer dedupeState.Unlock()
	if dedupeState.job.ID == id {
		now := time.Now()
		dedupeState.job.Finished = &now
		if failed {
			dedupeState.job.Status = "partial_failure"
		} else {
			dedupeState.job.Status = "complete"
		}
	}
}
