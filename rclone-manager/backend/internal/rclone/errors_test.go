package rclone

import (
	"errors"
	"strings"
	"testing"
)

func TestSummarizeRcloneError(t *testing.T) {
	cases := []struct{ input, want string }{
		{"write: no space left on device", "存储空间不足"},
		{"HTTP 429 too many requests", "云盘配额或请求频率受限"},
		{"dial tcp: connection refused", "网络连接失败"},
		{"invalid_grant", "云盘授权失效"},
		{"unknown error", "rclone 传输失败"},
	}
	for _, tc := range cases {
		if got := summarizeRcloneError(tc.input); got != tc.want {
			t.Errorf("%q: got %q, want %q", tc.input, got, tc.want)
		}
	}
}

func TestDescribeRcloneFailureKeepsDetails(t *testing.T) {
	err := describeRcloneFailure(errors.New("exit status 1"), "ERROR : disk full", 0, false)
	if !strings.Contains(err.Error(), "存储空间不足") || !strings.Contains(err.Error(), "disk full") {
		t.Fatal(err)
	}
}
