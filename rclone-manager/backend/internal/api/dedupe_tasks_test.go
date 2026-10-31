package api

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDedupeTaskTargetLocalFolderOnly(t *testing.T) {
	if _, _, err := dedupeTaskTarget("local", "", "/"); err == nil {
		t.Fatal("root directory must be rejected")
	}
	if _, _, err := dedupeTaskTarget("local", "", "relative/path"); err == nil {
		t.Fatal("relative path must be rejected")
	}
	directory := t.TempDir()
	got, target, err := dedupeTaskTarget("local", "", directory)
	if err != nil || got != target || got != directory {
		t.Fatalf("unexpected target: %q %q %v", got, target, err)
	}
	file := filepath.Join(directory, "movie.mkv")
	if err := os.WriteFile(file, []byte("test"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := dedupeTaskTarget("local", "", file); err == nil {
		t.Fatal("files must be rejected")
	}
}

func TestWithinDedupeRoot(t *testing.T) {
	if !withinDedupeRoot("/media/movies", "/media/movies/Drama") {
		t.Fatal("child folder should be allowed")
	}
	if withinDedupeRoot("/media/movies", "/media/movies2") || withinDedupeRoot("/media/movies", "/media") {
		t.Fatal("sibling and parent folders must be rejected")
	}
}
