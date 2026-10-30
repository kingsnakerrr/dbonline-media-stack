package rclone

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
)

// A cgroup OOM event is stronger evidence than a SIGKILL alone: the latter
// also occurs when an administrator or another program kills rclone.
func readOOMKillCount() (uint64, bool) {
	data, err := os.ReadFile("/sys/fs/cgroup/memory.events")
	if err != nil {
		return 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && fields[0] == "oom_kill" {
			count, err := strconv.ParseUint(fields[1], 10, 64)
			return count, err == nil
		}
	}
	return 0, false
}

func isUsefulRcloneError(line string) bool {
	lower := strings.ToLower(line)
	return strings.Contains(lower, "error :") || strings.Contains(lower, "failed to") ||
		strings.Contains(lower, "fatal error") || strings.Contains(lower, "out of memory")
}

func describeRcloneFailure(runErr error, stderr string, oomBefore uint64, oomReadable bool) error {
	if runErr == nil {
		return nil
	}
	raw := runErr.Error()
	var exitErr *exec.ExitError
	killed := false
	if errors.As(runErr, &exitErr) && exitErr.ProcessState != nil {
		if status, ok := exitErr.ProcessState.Sys().(syscall.WaitStatus); ok {
			killed = status.Signaled() && status.Signal() == syscall.SIGKILL
		}
	}
	if killed {
		if after, ok := readOOMKillCount(); ok && oomReadable && after > oomBefore {
			return fmt.Errorf("内存不足：系统 OOM 击杀了 rclone（原始错误：%s）", raw)
		}
		return fmt.Errorf("rclone 被强制终止；是否内存不足尚未确认（原始错误：%s）", raw)
	}
	if stderr != "" {
		return fmt.Errorf("%s（原始错误：%s；%s）", summarizeRcloneError(stderr), raw, stderr)
	}
	return fmt.Errorf("rclone 运行失败：%s", raw)
}

func summarizeRcloneError(line string) string {
	lower := strings.ToLower(line)
	switch {
	case strings.Contains(lower, "no space left"), strings.Contains(lower, "disk full"), strings.Contains(lower, "insufficient storage"):
		return "存储空间不足"
	case strings.Contains(lower, "permission denied"), strings.Contains(lower, "access denied"), strings.Contains(lower, "403 forbidden"):
		return "访问被拒绝，请检查权限"
	case strings.Contains(lower, "quota exceeded"), strings.Contains(lower, "rate limit"), strings.Contains(lower, "too many requests"), strings.Contains(lower, "429"):
		return "云盘配额或请求频率受限"
	case strings.Contains(lower, "connection refused"), strings.Contains(lower, "network is unreachable"), strings.Contains(lower, "i/o timeout"), strings.Contains(lower, "connection reset"):
		return "网络连接失败"
	case strings.Contains(lower, "failed to refresh token"), strings.Contains(lower, "invalid_grant"), strings.Contains(lower, "unauthorized"):
		return "云盘授权失效"
	default:
		return "rclone 传输失败"
	}
}
