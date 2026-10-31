package api

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestDeleteLocalBrowserItemRequiresExactSelectedType(t *testing.T) {
	root := t.TempDir()
	directory := filepath.Join(root, "folder")
	if err := os.Mkdir(directory, 0700); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(directory, "movie.mkv")
	if err := os.WriteFile(file, []byte("test"), 0600); err != nil {
		t.Fatal(err)
	}
	request := func(target string, isDir bool) int {
		writer := httptest.NewRecorder()
		context, _ := gin.CreateTestContext(writer)
		context.Request = httptest.NewRequest(http.MethodPost, "/files/delete", nil)
		deleteLocalBrowserItem(context, target, isDir)
		return writer.Code
	}
	if status := request(file, true); status != http.StatusConflict {
		t.Fatalf("wrong type should not delete file, got %d", status)
	}
	if _, err := os.Stat(file); err != nil {
		t.Fatalf("file unexpectedly removed: %v", err)
	}
	if status := request(file, false); status != http.StatusOK {
		t.Fatalf("file deletion failed: %d", status)
	}
	if status := request(directory, true); status != http.StatusOK {
		t.Fatalf("directory deletion failed: %d", status)
	}
	if _, err := os.Stat(directory); !os.IsNotExist(err) {
		t.Fatalf("directory should be gone: %v", err)
	}
}
