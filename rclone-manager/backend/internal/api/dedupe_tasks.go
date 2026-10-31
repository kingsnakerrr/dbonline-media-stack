package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"rclone-manager/internal/models"
)

var dedupeTaskRuns = struct {
	sync.Mutex
	cancel map[uint]context.CancelFunc
	runID  map[uint]uint
}{cancel: make(map[uint]context.CancelFunc), runID: make(map[uint]uint)}

// Only one destructive dedupe command may run at a time, even across tasks.
var dedupeTaskSlot = make(chan struct{}, 1)
var dedupeTaskLogMu sync.Mutex

func dedupeTaskTarget(sourceType, remote, rawPath string) (string, string, error) {
	if sourceType == "remote" {
		directory, err := validDedupeTarget(remote, rawPath)
		if err != nil || directory == "/" {
			return "", "", errors.New("请选择远端中的具体文件夹，不能选择整个网盘")
		}
		return directory, dedupeRemotePath(remote, directory), nil
	}
	if sourceType != "local" {
		return "", "", errors.New("来源只能是本地或网盘")
	}
	if strings.ContainsAny(rawPath, "\x00\r\n") || !filepath.IsAbs(rawPath) {
		return "", "", errors.New("请选择有效的本地绝对路径")
	}
	directory, err := filepath.EvalSymlinks(filepath.Clean(rawPath))
	if err != nil {
		return "", "", fmt.Errorf("读取本地目录失败：%w", err)
	}
	if directory == "/" {
		return "", "", errors.New("不能对整个本地根目录运行去重")
	}
	info, err := os.Stat(directory)
	if err != nil || !info.IsDir() {
		return "", "", errors.New("所选本地文件夹不存在")
	}
	return directory, directory, nil
}

func dedupeTaskView(task models.DedupeTask) gin.H {
	findings := []dedupeFinding{}
	logs := []string{}
	_ = json.Unmarshal([]byte(task.FindingsJSON), &findings)
	_ = json.Unmarshal([]byte(task.LogJSON), &logs)
	return gin.H{
		"id": task.ID, "name": task.Name, "source_type": task.SourceType,
		"remote": task.Remote, "path": task.Path, "mode": task.Mode,
		"interval_minutes": task.IntervalMinutes, "enabled": task.Enabled,
		"status": task.Status, "findings": findings, "logs": logs,
		"last_error": task.LastError, "last_run": task.LastRun,
		"next_run": task.NextRun, "created_at": task.CreatedAt,
	}
}

func dedupeTaskID(c *gin.Context) (uint, bool) {
	n, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil || n == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "无效任务 ID"})
		return 0, false
	}
	return uint(n), true
}

func listDedupeTasks(c *gin.Context) {
	var tasks []models.DedupeTask
	// One-shot tasks leave the active list after completion; their detail/log URL remains readable.
	if err := db.Where("status != ? AND (mode = ? OR status != ?)", "deleted", "scheduled", "complete").Order("created_at desc").Find(&tasks).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	views := make([]gin.H, 0, len(tasks))
	for _, task := range tasks {
		views = append(views, dedupeTaskView(task))
	}
	c.JSON(http.StatusOK, views)
}

func getDedupeTask(c *gin.Context) {
	id, ok := dedupeTaskID(c)
	if !ok {
		return
	}
	var task models.DedupeTask
	if err := db.First(&task, id).Error; err != nil || task.Status == "deleted" {
		c.JSON(http.StatusNotFound, gin.H{"error": "任务不存在"})
		return
	}
	c.JSON(http.StatusOK, dedupeTaskView(task))
}

func createDedupeTask(c *gin.Context) {
	var req struct {
		SourceType      string `json:"source_type"`
		Remote          string `json:"remote"`
		Path            string `json:"path"`
		Mode            string `json:"mode"`
		IntervalMinutes int    `json:"interval_minutes"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "任务参数无效"})
		return
	}
	if req.Mode != "scheduled" && req.Mode != "check" && req.Mode != "once" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请选择定时、检查或一次性去重"})
		return
	}
	directory, _, err := dedupeTaskTarget(req.SourceType, req.Remote, req.Path)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if req.Mode == "scheduled" && (req.IntervalMinutes < 5 || req.IntervalMinutes > 10080) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "定时间隔须在 5 分钟至 7 天之间"})
		return
	}
	if req.Mode == "scheduled" {
		var count int64
		db.Model(&models.DedupeTask{}).Where("source_type = ? AND remote = ? AND path = ? AND mode = ? AND status != ?", req.SourceType, req.Remote, directory, "scheduled", "deleted").Count(&count)
		if count > 0 {
			c.JSON(http.StatusConflict, gin.H{"error": "这个文件夹已有定时去重任务，请在任务管理中调整间隔"})
			return
		}
	}
	namePath := directory
	if req.SourceType == "remote" {
		namePath = req.Remote + directory
	}
	task := models.DedupeTask{
		Name: "去重合并" + namePath, SourceType: req.SourceType,
		Remote: req.Remote, Path: directory, Mode: req.Mode,
		IntervalMinutes: req.IntervalMinutes, Enabled: true, Status: "queued",
		FindingsJSON: "[]", LogJSON: "[]",
	}
	if err := db.Create(&task).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	launchDedupeTask(task.ID, nil)
	c.JSON(http.StatusAccepted, dedupeTaskView(task))
}

func updateDedupeTask(c *gin.Context) {
	id, ok := dedupeTaskID(c)
	if !ok {
		return
	}
	var task models.DedupeTask
	if db.First(&task, id).Error != nil || task.Mode != "scheduled" {
		c.JSON(http.StatusNotFound, gin.H{"error": "定时任务不存在"})
		return
	}
	var req struct {
		IntervalMinutes int `json:"interval_minutes"`
	}
	if c.ShouldBindJSON(&req) != nil || req.IntervalMinutes < 5 || req.IntervalMinutes > 10080 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "间隔须在 5 分钟至 7 天之间"})
		return
	}
	next := time.Now().Add(time.Duration(req.IntervalMinutes) * time.Minute)
	db.Model(&task).Updates(map[string]interface{}{"interval_minutes": req.IntervalMinutes, "next_run": next})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func startDedupeTask(c *gin.Context) {
	id, ok := dedupeTaskID(c)
	if !ok {
		return
	}
	var task models.DedupeTask
	if db.First(&task, id).Error != nil || task.Status == "deleted" || task.Status == "complete" {
		c.JSON(http.StatusNotFound, gin.H{"error": "任务不存在"})
		return
	}
	if task.Mode == "check" && task.Status == "ready" {
		c.JSON(http.StatusConflict, gin.H{"error": "检查结果已就绪，请在详情中选择去重范围"})
		return
	}
	db.Model(&task).Update("enabled", true)
	if !launchDedupeTask(id, nil) {
		c.JSON(http.StatusConflict, gin.H{"error": "任务已经运行"})
		return
	}
	c.JSON(http.StatusAccepted, gin.H{"ok": true})
}

func stopDedupeTask(c *gin.Context) {
	id, ok := dedupeTaskID(c)
	if !ok {
		return
	}
	dedupeTaskRuns.Lock()
	cancel := dedupeTaskRuns.cancel[id]
	dedupeTaskRuns.Unlock()
	if cancel != nil {
		cancel()
	}
	db.Model(&models.DedupeTask{}).Where("id = ?", id).Updates(map[string]interface{}{"enabled": false, "status": "stopped", "next_run": nil})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func deleteDedupeTask(c *gin.Context) {
	id, ok := dedupeTaskID(c)
	if !ok {
		return
	}
	dedupeTaskRuns.Lock()
	cancel := dedupeTaskRuns.cancel[id]
	dedupeTaskRuns.Unlock()
	if cancel != nil {
		cancel()
	}
	db.Model(&models.DedupeTask{}).Where("id = ?", id).Updates(map[string]interface{}{"enabled": false, "status": "deleted", "next_run": nil})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func applyCheckedDedupeTask(c *gin.Context) {
	id, ok := dedupeTaskID(c)
	if !ok {
		return
	}
	var task models.DedupeTask
	if db.First(&task, id).Error != nil || task.Mode != "check" || task.Status != "ready" {
		c.JSON(http.StatusConflict, gin.H{"error": "检查任务尚未完成或已过期"})
		return
	}
	var req struct {
		FindingIDs []string `json:"finding_ids"`
	}
	if c.ShouldBindJSON(&req) != nil || len(req.FindingIDs) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请先选择要处理的项目"})
		return
	}
	var findings []dedupeFinding
	if json.Unmarshal([]byte(task.FindingsJSON), &findings) != nil {
		c.JSON(http.StatusConflict, gin.H{"error": "检查结果不可用，请重新检查"})
		return
	}
	valid := make(map[string]dedupeFinding)
	for _, finding := range findings {
		if finding.Kind == "merge" || finding.Kind == "empty" {
			valid[finding.ID] = finding
		}
	}
	selected := make([]dedupeFinding, 0, len(req.FindingIDs))
	seen := make(map[string]bool)
	for _, findingID := range req.FindingIDs {
		finding, exists := valid[findingID]
		if !exists || seen[findingID] || !withinDedupeRoot(task.Path, finding.Scope) {
			c.JSON(http.StatusBadRequest, gin.H{"error": "选中的项目不属于这次检查"})
			return
		}
		seen[findingID] = true
		selected = append(selected, finding)
	}
	if !launchDedupeTask(id, selected) {
		c.JSON(http.StatusConflict, gin.H{"error": "任务已经运行"})
		return
	}
	c.JSON(http.StatusAccepted, gin.H{"ok": true})
}

func appendDedupeTaskLog(id uint, message string) {
	dedupeTaskLogMu.Lock()
	defer dedupeTaskLogMu.Unlock()
	var task models.DedupeTask
	if db.Select("id", "log_json", "status").First(&task, id).Error != nil || task.Status == "deleted" {
		return
	}
	var logs []string
	_ = json.Unmarshal([]byte(task.LogJSON), &logs)
	if len(message) > 1000 {
		message = message[:1000]
	}
	logs = append(logs, time.Now().Format("15:04:05")+"  "+message)
	if len(logs) > 200 {
		logs = logs[len(logs)-200:]
	}
	data, _ := json.Marshal(logs)
	db.Model(&models.DedupeTask{}).Where("id = ?", id).Update("log_json", string(data))
	dedupeTaskRuns.Lock()
	runID := dedupeTaskRuns.runID[id]
	dedupeTaskRuns.Unlock()
	if runID != 0 {
		var run models.DedupeRun
		if db.Select("id", "log_json").First(&run, runID).Error == nil {
			var runLogs []string
			_ = json.Unmarshal([]byte(run.LogJSON), &runLogs)
			runLogs = append(runLogs, logs[len(logs)-1])
			data, _ := json.Marshal(runLogs)
			db.Model(&models.DedupeRun{}).Where("id = ?", runID).Update("log_json", string(data))
		}
	}
}

func setDedupeTaskStatus(id uint, status string) {
	db.Model(&models.DedupeTask{}).Where("id = ? AND status != ?", id, "deleted").Update("status", status)
}

func launchDedupeTask(id uint, selected []dedupeFinding) bool {
	dedupeTaskRuns.Lock()
	if dedupeTaskRuns.cancel[id] != nil {
		dedupeTaskRuns.Unlock()
		return false
	}
	ctx, cancel := context.WithCancel(context.Background())
	dedupeTaskRuns.cancel[id] = cancel
	var task models.DedupeTask
	if db.First(&task, id).Error != nil {
		delete(dedupeTaskRuns.cancel, id)
		dedupeTaskRuns.Unlock()
		cancel()
		return false
	}
	action := "检查重复"
	if selected != nil {
		action = "检查后执行选中项"
	} else if task.Mode != "check" {
		action = "检查并自动去重"
	}
	target := task.Path
	if task.SourceType == "remote" {
		target = task.Remote + ":" + task.Path
	}
	run := models.DedupeRun{TaskID: id, TaskName: task.Name, Mode: task.Mode, Target: target, Action: action, Status: "queued", LogJSON: "[]", OperationsJSON: "[]", StartedAt: time.Now()}
	if db.Create(&run).Error != nil {
		delete(dedupeTaskRuns.cancel, id)
		dedupeTaskRuns.Unlock()
		cancel()
		return false
	}
	dedupeTaskRuns.runID[id] = run.ID
	dedupeTaskRuns.Unlock()
	setDedupeTaskStatus(id, "queued")
	go func() {
		defer func() {
			cancel()
			dedupeTaskRuns.Lock()
			delete(dedupeTaskRuns.cancel, id)
			delete(dedupeTaskRuns.runID, id)
			dedupeTaskRuns.Unlock()
		}()
		select {
		case dedupeTaskSlot <- struct{}{}:
			defer func() { <-dedupeTaskSlot }()
		case <-ctx.Done():
			finishDedupeRun(run.ID, "cancelled", "任务在排队时已取消")
			return
		}
		done := make(chan struct{})
		defer close(done)
		go func() {
			ticker := time.NewTicker(30 * time.Second)
			defer ticker.Stop()
			for {
				select {
				case <-ticker.C:
					var task models.DedupeTask
					if db.Select("status").First(&task, id).Error == nil && (task.Status == "scanning" || task.Status == "applying") {
						appendDedupeTaskLog(id, "仍在运行："+task.Status+"；大型目录可能需要较长时间")
					}
				case <-done:
					return
				}
			}
		}()
		runDedupeTask(ctx, id, run.ID, selected)
	}()
	return true
}

func scanDedupeTask(ctx context.Context, id, runID uint, task models.DedupeTask, target string) ([]dedupeFinding, error) {
	setDedupeTaskStatus(id, "scanning")
	db.Model(&models.DedupeRun{}).Where("id = ?", runID).Update("status", "scanning")
	appendDedupeTaskLog(id, "开始检查重复目录和文件："+target)
	output, err := runDedupeRclone(ctx, 16<<20, "dedupe", "list", target, "--config", dedupeConfig, "--log-level", "ERROR")
	if err != nil {
		return nil, err
	}
	findings := parseDedupeList(output, task.Path)
	duplicateCount := len(findings)
	appendDedupeTaskLog(id, fmt.Sprintf("发现 %d 个重复范围；继续检查空目录", duplicateCount))
	listing, err := runDedupeRclone(ctx, 32<<20, "lsjson", target, "--recursive", "--config", dedupeConfig)
	if err == nil {
		var empty []dedupeFinding
		empty, err = emptyDedupeDirs(listing, task.Path)
		findings = append(findings, empty...)
	}
	if err != nil {
		appendDedupeTaskLog(id, "空目录检查未完成："+err.Error())
	}
	for i := range findings {
		if findings[i].Kind == "merge" {
			appendDedupeTaskLog(id, fmt.Sprintf("同名%s：%s；%d 份", findings[i].ItemType, findings[i].Path, findings[i].Count))
		}
	}
	data, _ := json.Marshal(findings)
	db.Model(&models.DedupeTask{}).Where("id = ?", id).Update("findings_json", string(data))
	appendDedupeTaskLog(id, fmt.Sprintf("检查完成：同名项目 %d，空目录 %d", duplicateCount, len(findings)-duplicateCount))
	return findings, nil
}

func applyDedupeTaskFindings(ctx context.Context, id, runID uint, task models.DedupeTask, work []dedupeFinding) error {
	setDedupeTaskStatus(id, "applying")
	db.Model(&models.DedupeRun{}).Where("id = ?", runID).Update("status", "applying")
	sort.Slice(work, func(i, j int) bool {
		if work[i].Kind != work[j].Kind {
			return work[i].Kind == "merge"
		}
		if work[i].Kind == "empty" {
			return len(work[i].Scope) > len(work[j].Scope)
		}
		return len(work[i].Scope) < len(work[j].Scope)
	})
	var failures []string
	for index, finding := range work {
		if err := ctx.Err(); err != nil {
			return err
		}
		target := finding.Scope
		if task.SourceType == "remote" {
			target = dedupeRemotePath(task.Remote, finding.Scope)
		}
		args := []string{"dedupe", "newest", target, "--config", dedupeConfig}
		operation := dedupeOperation{Path: finding.Path, Kind: finding.Kind, ItemType: finding.ItemType, Status: "running", Command: "rclone dedupe newest " + target}
		if finding.Kind == "empty" {
			emptyTarget := finding.Path
			if task.SourceType == "remote" {
				emptyTarget = dedupeRemotePath(task.Remote, finding.Path)
			}
			operation.Command = "rclone rmdir " + emptyTarget + "（执行前逐份确认仍为空）"
			var emptyErr error
			operation.Output, emptyErr = removeEmptyDedupeDirectories(ctx, task, finding)
			if emptyErr != nil {
				operation.Status, operation.Error, operation.Summary = "skipped", emptyErr.Error(), "安全检查未通过，未继续删除此目录"
				if operation.Output != "" {
					operation.Status, operation.Summary = "failed", "部分空目录已处理；后续副本安全检查失败，已停止"
					failures = append(failures, finding.Path+": "+emptyErr.Error())
				}
				appendDedupeTaskLog(id, "跳过空目录："+finding.Path+"；"+emptyErr.Error())
			} else {
				operation.Status, operation.Summary = "complete", "已删除所有核实为空的目录副本"
				appendDedupeTaskLog(id, "完成："+finding.Path+"；"+operation.Summary)
			}
			appendDedupeRunOperation(runID, operation)
			continue
		}
		if finding.Kind == "merge" {
			filters, filterErr := dedupeItemFilters(finding)
			if filterErr != nil {
				failures = append(failures, finding.Path+": "+filterErr.Error())
				appendDedupeTaskLog(id, "失败："+failures[len(failures)-1])
				continue
			}
			args = append(args, filters...)
			operation.Command += " --filter '仅匹配 " + path.Base(finding.Path) + "'"
			operation.Before, _ = inspectDedupeFinding(ctx, task, finding)
			live, liveErr := runDedupeRclone(ctx, 2<<20, append([]string{"dedupe", "list", target, "--config", dedupeConfig}, filters...)...)
			if liveErr != nil {
				failures = append(failures, finding.Path+": "+liveErr.Error())
				operation.Status = "failed"
				operation.Error = liveErr.Error()
				appendDedupeRunOperation(runID, operation)
				continue
			}
			liveFindings := parseDedupeList(live, finding.Scope)
			if len(liveFindings) == 0 {
				operation.Status = "skipped"
				operation.Output = "执行前重复项已消失"
				appendDedupeRunOperation(runID, operation)
				appendDedupeTaskLog(id, "跳过："+finding.Path+"，已无重复项")
				continue
			}
			for _, item := range liveFindings {
				if item.Path != finding.Path && !withinDedupeRoot(finding.Path, item.Path) {
					liveErr = errors.New("过滤结果包含选中目录以外的重复项，已停止以避免误处理")
					break
				}
			}
			if liveErr != nil {
				failures = append(failures, finding.Path+": "+liveErr.Error())
				operation.Status = "failed"
				operation.Error = liveErr.Error()
				appendDedupeRunOperation(runID, operation)
				continue
			}
		}
		appendDedupeTaskLog(id, fmt.Sprintf("[%d/%d] 预演 %s", index+1, len(work), target))
		_, err := runDedupeRclone(ctx, 1<<20, append(append([]string{}, args...), "--dry-run")...)
		if err == nil {
			appendDedupeTaskLog(id, fmt.Sprintf("[%d/%d] 处理 %s", index+1, len(work), target))
			operation.Output, err = runDedupeRclone(ctx, 16<<20, append(args, "--log-level", "INFO")...)
		}
		if len(operation.Output) > 12000 {
			operation.Output = operation.Output[:12000] + "\n…输出已截断"
		}
		if finding.Kind == "merge" {
			operation.After, _ = inspectDedupeFinding(ctx, task, finding)
		}
		operation.Summary = summarizeDedupeOperation(operation.Before, operation.After)
		if err != nil {
			failures = append(failures, target+": "+err.Error())
			operation.Status = "failed"
			operation.Error = err.Error()
			appendDedupeTaskLog(id, "失败："+failures[len(failures)-1])
		} else {
			operation.Status = "complete"
			appendDedupeTaskLog(id, "完成："+finding.Path+"；"+operation.Summary)
		}
		appendDedupeRunOperation(runID, operation)
	}
	if len(failures) > 0 {
		return errors.New(strings.Join(failures, "; "))
	}
	return nil
}

func runDedupeTask(parent context.Context, id, runID uint, selected []dedupeFinding) {
	ctx, cancel := context.WithTimeout(parent, 2*time.Hour)
	defer cancel()
	var task models.DedupeTask
	if db.First(&task, id).Error != nil || task.Status == "deleted" {
		finishDedupeRun(runID, "cancelled", "任务已删除")
		return
	}
	_, target, err := dedupeTaskTarget(task.SourceType, task.Remote, task.Path)
	if err == nil {
		if selected == nil {
			var findings []dedupeFinding
			findings, err = scanDedupeTask(ctx, id, runID, task, target)
			if err == nil && task.Mode == "check" {
				setDedupeTaskStatus(id, "ready")
				appendDedupeTaskLog(id, fmt.Sprintf("检查完毕，%d 项可在详情中选择处理", len(findings)))
				finishDedupeRun(runID, "complete", fmt.Sprintf("检查完成：%d 个可处理范围", len(findings)))
				return
			}
			if err == nil {
				// Apply individual findings so that the five-day guard also applies
				// to scheduled and one-shot jobs; never run blanket rmdirs.
				for _, finding := range findings {
					if finding.Kind == "merge" || finding.Kind == "empty" {
						selected = append(selected, finding)
					}
				}
			}
		}
		if err == nil {
			err = applyDedupeTaskFindings(ctx, id, runID, task, selected)
		}
	}
	if ctx.Err() != nil {
		err = ctx.Err()
	}
	now := time.Now()
	updates := map[string]interface{}{"last_run": now}
	var current models.DedupeTask
	_ = db.First(&current, id).Error
	if current.Status == "stopped" {
		updates["status"] = "stopped"
	} else if task.Mode == "scheduled" {
		if current.ID != 0 && current.Enabled {
			next := now.Add(time.Duration(current.IntervalMinutes) * time.Minute)
			updates["next_run"] = next
			if err != nil {
				updates["status"] = "error"
			} else {
				updates["status"] = "idle"
			}
		} else {
			updates["status"] = "stopped"
		}
	} else if err == nil {
		updates["status"] = "complete"
	} else {
		updates["status"] = "error"
	}
	if err != nil {
		updates["last_error"] = err.Error()
		appendDedupeTaskLog(id, "任务失败："+err.Error())
	} else {
		updates["last_error"] = ""
		appendDedupeTaskLog(id, "任务完成")
	}
	if errors.Is(err, context.Canceled) {
		finishDedupeRun(runID, "cancelled", "用户已停止任务")
	} else if err != nil {
		finishDedupeRun(runID, "failed", err.Error())
	} else {
		finishDedupeRun(runID, "complete", "处理完成，详细结果见本次运行记录")
	}
	db.Model(&models.DedupeTask{}).Where("id = ? AND status != ?", id, "deleted").Updates(updates)
}

func startDedupeTaskSchedule() {
	// Interrupted work is not silently resumed. A scheduled job receives a new
	// interval; a one-shot job remains visible for explicit retry.
	db.Model(&models.DedupeTask{}).Where("status IN ?", []string{"queued", "scanning", "applying"}).Update("status", "error")
	db.Model(&models.DedupeRun{}).Where("status IN ?", []string{"queued", "scanning", "applying"}).Updates(map[string]interface{}{"status": "interrupted", "summary": "服务重启中断了本次运行；请重新检查后再处理", "finished_at": time.Now()})
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			var tasks []models.DedupeTask
			db.Where("mode = ? AND enabled = ? AND (next_run IS NULL OR next_run <= ?)", "scheduled", true, time.Now()).Find(&tasks)
			for _, task := range tasks {
				if task.Status == "queued" || task.Status == "scanning" || task.Status == "applying" {
					continue
				}
				if launchDedupeTask(task.ID, nil) {
					next := time.Now().Add(time.Duration(task.IntervalMinutes) * time.Minute)
					db.Model(&task).Update("next_run", next)
				}
			}
		}
	}()
}
