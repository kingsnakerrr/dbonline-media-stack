package api

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// Keep folder scans off the directory-listing request and limit disk I/O when
// several browser tabs request sizes at once.
var localSizeScans = make(chan struct{}, 2)

func getLocalFolderSize(c *gin.Context) {
	path := c.Query("path")
	if path == "" || !filepath.IsAbs(path) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "absolute folder path required"})
		return
	}
	rootAbs, err := filepath.Abs(localBrowserRoot)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	pathAbs, err := filepath.Abs(filepath.Clean(path))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	rel, err := filepath.Rel(rootAbs, pathAbs)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		c.JSON(http.StatusForbidden, gin.H{"error": "folder outside local browser root"})
		return
	}
	info, err := os.Lstat(pathAbs)
	if err != nil || !info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": "folder does not exist or is a symbolic link"})
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 45*time.Second)
	defer cancel()
	select {
	case localSizeScans <- struct{}{}:
		defer func() { <-localSizeScans }()
	case <-ctx.Done():
		c.JSON(http.StatusRequestTimeout, gin.H{"error": "folder size timed out"})
		return
	}

	size, err := calculateLocalFolderSize(ctx, pathAbs)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": fmt.Sprintf("could not calculate folder size: %v", err)})
		return
	}
	c.JSON(http.StatusOK, gin.H{"path": pathAbs, "size": size})
}

// Report allocated disk usage, matching `du`, rather than apparent file size.
// This matters for sparse, incomplete torrent files. -x avoids crossing into
// other filesystems and du does not follow symlinks by default.
func calculateLocalFolderSize(ctx context.Context, root string) (int64, error) {
	output, err := exec.CommandContext(ctx, "du", "-skx", root).Output()
	if ctx.Err() != nil {
		return 0, ctx.Err()
	}
	if err != nil {
		return 0, err
	}
	fields := strings.Fields(string(output))
	if len(fields) == 0 {
		return 0, fmt.Errorf("empty du result")
	}
	kib, err := strconv.ParseInt(fields[0], 10, 64)
	if err != nil {
		return 0, err
	}
	return kib * 1024, nil
}
