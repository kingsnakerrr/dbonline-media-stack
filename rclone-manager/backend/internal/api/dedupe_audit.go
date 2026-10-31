package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"rclone-manager/internal/models"
)

// A copy is identified by the backend's directory ID when available. The
// fallback is explicitly labelled as a combined view, never as one copy.
type dedupeContentEntry struct {
	Path  string `json:"path"`
	Size  int64  `json:"size"`
	IsDir bool   `json:"is_dir"`
}

type dedupeCopyContents struct {
	ID        string               `json:"id,omitempty"`
	Label     string               `json:"label"`
	Entries   []dedupeContentEntry `json:"entries"`
	Truncated bool                 `json:"truncated,omitempty"`
	Error     string               `json:"error,omitempty"`
}

type dedupeOperation struct {
	Path     string               `json:"path"`
	Kind     string               `json:"kind"`
	ItemType string               `json:"item_type,omitempty"`
	Status   string               `json:"status"`
	Summary  string               `json:"summary,omitempty"`
	Before   []dedupeCopyContents `json:"before"`
	After    []dedupeCopyContents `json:"after"`
	Command  string               `json:"command"`
	Output   string               `json:"output"`
	Error    string               `json:"error,omitempty"`
}

func summarizeDedupeOperation(before, after []dedupeCopyContents) string {
	if len(before) == 0 && len(after) == 0 {
		return "未取得可比较的文件清单，请查看 rclone 原始输出"
	}
	countEntries := func(copies []dedupeCopyContents) int {
		total := 0
		for _, copy := range copies {
			total += len(copy.Entries)
		}
		return total
	}
	return fmt.Sprintf("处理前 %d 个可见目录副本、%d 项内容；处理后 %d 个可见目录副本、%d 项内容。下方逐份列出原有内容和最终保留内容。", len(before), countEntries(before), len(after), countEntries(after))
}

type rcloneJSONEntry struct {
	Path     string            `json:"Path"`
	Name     string            `json:"Name"`
	ID       string            `json:"ID"`
	Size     int64             `json:"Size"`
	IsDir    bool              `json:"IsDir"`
	ModTime  string            `json:"ModTime"`
	Metadata map[string]string `json:"Metadata"`
}

var errDedupeDirGone = errors.New("目录已不存在，请重新检查")

func listDedupeJSON(ctx context.Context, target string, args ...string) ([]rcloneJSONEntry, error) {
	command := append([]string{"lsjson", target, "--config", dedupeConfig}, args...)
	output, err := runDedupeRclone(ctx, 8<<20, command...)
	if err != nil {
		return nil, err
	}
	var entries []rcloneJSONEntry
	if err := json.Unmarshal([]byte(output), &entries); err != nil {
		return nil, err
	}
	return entries, nil
}

func matchingDedupeDirectories(ctx context.Context, task models.DedupeTask, finding dedupeFinding) ([]rcloneJSONEntry, error) {
	parent := finding.Scope
	if finding.Kind == "empty" {
		parent = path.Dir(finding.Path)
	}
	if task.SourceType == "remote" {
		parent = dedupeRemotePath(task.Remote, parent)
	}
	entries, err := listDedupeJSON(ctx, parent, "--dirs-only")
	if err != nil {
		return nil, err
	}
	var matches []rcloneJSONEntry
	for _, entry := range entries {
		if entry.IsDir && entry.Name == path.Base(finding.Path) {
			matches = append(matches, entry)
		}
	}
	if len(matches) == 0 {
		return nil, errDedupeDirGone
	}
	return matches, nil
}

func validateEmptyDedupeDirectory(ctx context.Context, task models.DedupeTask, finding dedupeFinding) (int, error) {
	if task.SourceType == "local" {
		info, err := os.Stat(finding.Path)
		if err != nil {
			return 0, err
		}
		if !info.IsDir() {
			return 0, errors.New("目标不是目录")
		}
		entries, err := os.ReadDir(finding.Path)
		if err != nil {
			return 0, err
		}
		if len(entries) != 0 {
			return 0, errors.New("目录已有内容，不删除")
		}
		return 1, nil
	}
	matches, err := matchingDedupeDirectories(ctx, task, finding)
	if err != nil {
		return 0, err
	}
	if len(matches) > 1 && !isDriveDedupeRemote(task.Remote) {
		return 0, errors.New("远端无法逐份核对同名空目录，跳过删除")
	}
	for _, copy := range matches {
		copyTarget := dedupeRemotePath(task.Remote, finding.Path)
		if isDriveDedupeRemote(task.Remote) {
			if !safeRemoteID.MatchString(copy.ID) {
				return 0, errors.New("无法核对目录副本 ID，跳过删除")
			}
			copyTarget = task.Remote + ",root_folder_id=" + copy.ID + ":"
		}
		children, err := listDedupeJSON(ctx, copyTarget)
		if err != nil {
			return 0, err
		}
		if len(children) != 0 {
			return 0, errors.New("至少一个同名目录已有内容，不删除")
		}
	}
	return len(matches), nil
}

func removeEmptyDedupeDirectories(ctx context.Context, task models.DedupeTask, finding dedupeFinding) (string, error) {
	target := finding.Path
	if task.SourceType == "remote" {
		target = dedupeRemotePath(task.Remote, finding.Path)
	}
	var output strings.Builder
	for attempt := 0; attempt < 100; attempt++ {
		copies, err := validateEmptyDedupeDirectory(ctx, task, finding)
		if err != nil {
			if attempt > 0 && errors.Is(err, errDedupeDirGone) {
				return output.String(), nil
			}
			return output.String(), err
		}
		if copies > 100 {
			return output.String(), errors.New("同名空目录超过安全处理上限 100 个")
		}
		args := []string{"rmdir", target, "--config", dedupeConfig}
		if _, err := runDedupeRclone(ctx, 1<<20, append(append([]string{}, args...), "--dry-run")...); err != nil {
			return output.String(), err
		}
		result, err := runDedupeRclone(ctx, 1<<20, append(args, "--log-level", "INFO")...)
		output.WriteString(fmt.Sprintf("第 %d 次删除空目录（执行前再次确认仍为空）\n%s\n", attempt+1, result))
		if err != nil {
			return output.String(), err
		}
		if task.SourceType == "local" {
			return output.String(), nil
		}
	}
	return output.String(), errors.New("达到 100 次处理上限，仍有同名目录；请重新检查")
}

var safeRemoteID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,200}$`)

func isDriveDedupeRemote(remote string) bool {
	config, err := os.ReadFile(dedupeConfig)
	if err != nil {
		return false
	}
	section := ""
	for _, line := range strings.Split(string(config), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			section = strings.Trim(line, "[]")
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if ok && section == remote && strings.TrimSpace(key) == "type" && strings.EqualFold(strings.TrimSpace(value), "drive") {
			return true
		}
	}
	return false
}

func escapeDedupeGlob(name string) string {
	var out strings.Builder
	for _, char := range name {
		if strings.ContainsRune(`\\*?[]{} `, char) && char != ' ' {
			out.WriteByte('\\')
		}
		out.WriteRune(char)
	}
	return out.String()
}

func dedupeItemFilters(finding dedupeFinding) ([]string, error) {
	name := strings.TrimPrefix(finding.Path, strings.TrimSuffix(finding.Scope, "/")+"/")
	if name == "" || name == finding.Path || strings.Contains(name, "/") || strings.ContainsAny(name, "\r\n") {
		return nil, errors.New("无法确定单组重复项的名称")
	}
	pattern := "/" + escapeDedupeGlob(name)
	if finding.ItemType != "同名文件" {
		pattern += "/**"
	}
	return []string{"--filter", "+ " + pattern, "--filter", "- **"}, nil
}

func dedupeEntries(raw string) ([]dedupeContentEntry, bool, error) {
	var items []rcloneJSONEntry
	if err := json.Unmarshal([]byte(raw), &items); err != nil {
		return nil, false, err
	}
	entries := make([]dedupeContentEntry, 0, min(len(items), 500))
	for index, item := range items {
		if index >= 500 {
			break
		}
		entries = append(entries, dedupeContentEntry{Path: item.Path, Size: item.Size, IsDir: item.IsDir})
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Path < entries[j].Path })
	return entries, len(items) > 500, nil
}

func inspectDedupeFinding(ctx context.Context, task models.DedupeTask, finding dedupeFinding) ([]dedupeCopyContents, string) {
	if finding.Kind == "empty" {
		return []dedupeCopyContents{}, "扫描时为空；执行前会再次检查"
	}
	filters, err := dedupeItemFilters(finding)
	if err != nil {
		return nil, err.Error()
	}
	parent := finding.Scope
	if task.SourceType == "remote" {
		parent = dedupeRemotePath(task.Remote, finding.Scope)
	}
	if finding.ItemType == "同名目录" && task.SourceType == "remote" && isDriveDedupeRemote(task.Remote) {
		output, listErr := runDedupeRclone(ctx, 8<<20, "lsjson", parent, "--dirs-only", "--config", dedupeConfig)
		if listErr == nil {
			var dirs []rcloneJSONEntry
			if json.Unmarshal([]byte(output), &dirs) == nil {
				copies := []dedupeCopyContents{}
				for _, dir := range dirs {
					if dir.Name != path.Base(finding.Path) || !safeRemoteID.MatchString(dir.ID) {
						continue
					}
					copy := dedupeCopyContents{ID: dir.ID, Label: fmt.Sprintf("副本 %d · ID %s", len(copies)+1, dir.ID), Entries: []dedupeContentEntry{}}
					copyTarget := task.Remote + ",root_folder_id=" + dir.ID + ":"
					listed, listErr := runDedupeRclone(ctx, 4<<20, "lsjson", copyTarget, "--recursive", "--config", dedupeConfig)
					if listErr != nil {
						copy.Error = listErr.Error()
					} else {
						copy.Entries, copy.Truncated, listErr = dedupeEntries(listed)
						if listErr != nil {
							copy.Error = listErr.Error()
						}
					}
					copies = append(copies, copy)
					if len(copies) >= 12 {
						return copies, "仅展示前 12 个同名目录副本"
					}
				}
				if len(copies) > 0 {
					return copies, "按网盘目录 ID 分别列出；每个副本最多展示 500 项"
				}
			}
		}
	}
	args := append([]string{"lsjson", parent, "--recursive", "--config", dedupeConfig}, filters...)
	listed, err := runDedupeRclone(ctx, 4<<20, args...)
	if err != nil {
		return nil, "读取合并视图失败：" + err.Error()
	}
	entries, truncated, err := dedupeEntries(listed)
	if err != nil {
		return nil, "解析内容失败：" + err.Error()
	}
	return []dedupeCopyContents{{Label: "同名路径下的合并视图（无法区分物理副本）", Entries: entries, Truncated: truncated}}, "此远端未提供可逐一访问的目录 ID；下列是合并视图"
}

func dedupeRunView(run models.DedupeRun, includeDetails bool) gin.H {
	view := gin.H{"id": run.ID, "task_id": run.TaskID, "task_name": run.TaskName, "mode": run.Mode, "target": run.Target, "action": run.Action, "status": run.Status, "summary": run.Summary, "started_at": run.StartedAt, "finished_at": run.FinishedAt}
	if includeDetails {
		logs := []string{}
		operations := []dedupeOperation{}
		_ = json.Unmarshal([]byte(run.LogJSON), &logs)
		_ = json.Unmarshal([]byte(run.OperationsJSON), &operations)
		view["logs"] = logs
		view["operations"] = operations
	}
	return view
}

func listDedupeRuns(c *gin.Context) {
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	if page < 1 {
		page = 1
	}
	var total int64
	var runs []models.DedupeRun
	query := db.Model(&models.DedupeRun{})
	if id := c.Query("task_id"); id != "" {
		query = query.Where("task_id = ?", id)
	}
	query.Count(&total)
	if err := query.Order("id desc").Limit(20).Offset((page - 1) * 20).Find(&runs).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	views := make([]gin.H, 0, len(runs))
	for _, run := range runs {
		views = append(views, dedupeRunView(run, false))
	}
	c.JSON(http.StatusOK, gin.H{"list": views, "total": total})
}

func getDedupeRun(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil || id == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "无效运行 ID"})
		return
	}
	var run models.DedupeRun
	if db.First(&run, id).Error != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "运行记录不存在"})
		return
	}
	c.JSON(http.StatusOK, dedupeRunView(run, true))
}

func finishDedupeRun(id uint, status, summary string) {
	if id == 0 {
		return
	}
	now := time.Now()
	db.Model(&models.DedupeRun{}).Where("id = ?", id).Updates(map[string]interface{}{"status": status, "summary": summary, "finished_at": now})
}

func appendDedupeRunOperation(id uint, operation dedupeOperation) {
	if id == 0 {
		return
	}
	dedupeTaskLogMu.Lock()
	defer dedupeTaskLogMu.Unlock()
	var run models.DedupeRun
	if db.Select("id", "operations_json").First(&run, id).Error != nil {
		return
	}
	var operations []dedupeOperation
	_ = json.Unmarshal([]byte(run.OperationsJSON), &operations)
	operations = append(operations, operation)
	data, _ := json.Marshal(operations)
	db.Model(&models.DedupeRun{}).Where("id = ?", id).Update("operations_json", string(data))
}
