package api

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestCalculateLocalFolderSize(t *testing.T) {
	root := t.TempDir()
	child := filepath.Join(root, "child")
	if err := os.Mkdir(child, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "a"), []byte("12345"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(child, "b"), []byte("123"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(root, "a"), filepath.Join(child, "link")); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "large")
	if err := os.WriteFile(outside, make([]byte, 2*1024*1024), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "outside-link")); err != nil {
		t.Fatal(err)
	}
	size, err := calculateLocalFolderSize(context.Background(), root)
	if err != nil || size < 8 || size >= 2*1024*1024 {
		t.Fatalf("allocated size = %d, err = %v; want small nonzero size without symlink target", size, err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := calculateLocalFolderSize(ctx, root); err != context.Canceled {
		t.Fatalf("canceled scan error = %v", err)
	}
}
