package api

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
	"rclone-manager/internal/models"
)

// deleteBrowserItem deletes only an explicitly selected item. On remotes, a
// name must resolve to exactly one entry; duplicate Drive objects cannot be
// safely addressed by their shared path through the file browser.
func deleteBrowserItem(c *gin.Context) {
	var request struct {
		SourceType string `json:"source_type"`
		Remote     string `json:"remote"`
		Path       string `json:"path"`
		IsDir      bool   `json:"is_dir"`
		Username   string `json:"username"`
		Password   string `json:"password"`
	}
	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请选择要删除的文件或目录"})
		return
	}
	if request.Username == "" || request.Password == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "删除前请输入管理员密码"})
		return
	}
	var user models.User
	if db.Where("username = ? AND is_admin = ?", request.Username, true).First(&user).Error != nil || bcrypt.CompareHashAndPassword([]byte(user.Password), []byte(request.Password)) != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "管理员身份验证失败，未删除任何项目"})
		return
	}
	if request.SourceType == "local" {
		deleteLocalBrowserItem(c, request.Path, request.IsDir)
		return
	}
	if request.SourceType != "remote" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "无效的存储类型"})
		return
	}
	directory, err := validDedupeTarget(request.Remote, request.Path)
	if err != nil || directory == "/" || strings.TrimSpace(request.Path) == "" || strings.HasSuffix(request.Path, "/") {
		c.JSON(http.StatusBadRequest, gin.H{"error": "无效的远端项目路径"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Minute)
	defer cancel()
	parent := dedupeRemotePath(request.Remote, path.Dir(directory))
	entries, err := listDedupeJSON(ctx, parent)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "无法核对待删除项目：" + err.Error()})
		return
	}
	count := 0
	for _, entry := range entries {
		if entry.Name == path.Base(directory) {
			count++
			if entry.IsDir != request.IsDir {
				c.JSON(http.StatusConflict, gin.H{"error": "项目类型已变化，请刷新目录后重试"})
				return
			}
		}
	}
	if count != 1 {
		c.JSON(http.StatusConflict, gin.H{"error": fmt.Sprintf("该路径匹配 %d 个项目；可能存在同名副本，请勿按路径删除", count)})
		return
	}
	target := dedupeRemotePath(request.Remote, directory)
	command := "deletefile"
	if request.IsDir {
		command = "purge"
	}
	args := []string{command, target, "--config", dedupeConfig}
	if _, err := runDedupeRclone(ctx, 1<<20, append(append([]string{}, args...), "--dry-run")...); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "删除预演失败：" + err.Error()})
		return
	}
	if _, err := runDedupeRclone(ctx, 2<<20, args...); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "删除失败：" + err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "已删除"})
}

func deleteLocalBrowserItem(c *gin.Context, rawPath string, isDir bool) {
	if rawPath == "" || !filepath.IsAbs(rawPath) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "本地路径必须是绝对路径"})
		return
	}
	root, err := filepath.Abs(localBrowserRoot)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	target := filepath.Clean(rawPath)
	rel, err := filepath.Rel(root, target)
	if err != nil || rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		c.JSON(http.StatusForbidden, gin.H{"error": "不能删除存储根目录或其外部项目"})
		return
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(target))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "无法核对父目录：" + err.Error()})
		return
	}
	resolved := filepath.Join(parent, filepath.Base(target))
	resolvedRel, err := filepath.Rel(root, resolved)
	if err != nil || resolvedRel == "." || resolvedRel == ".." || strings.HasPrefix(resolvedRel, ".."+string(os.PathSeparator)) {
		c.JSON(http.StatusForbidden, gin.H{"error": "目录超出允许范围"})
		return
	}
	info, err := os.Lstat(resolved)
	if err != nil || info.IsDir() != isDir {
		c.JSON(http.StatusConflict, gin.H{"error": "项目不存在或类型已变化，请刷新目录后重试"})
		return
	}
	if isDir {
		err = os.RemoveAll(resolved)
	} else {
		err = os.Remove(resolved)
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "删除失败：" + err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "已删除"})
}
