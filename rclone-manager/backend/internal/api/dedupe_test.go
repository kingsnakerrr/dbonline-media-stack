package api

import (
	"strings"
	"testing"
)

func TestParseDedupeListKeepsEachFolderSelectable(t *testing.T) {
	output := strings.Join([]string{
		"Movies/Film: 2 duplicates of this directory",
		"Movies/Other: 2 duplicates of this directory",
		"Movies/Film/movie.mkv: 2 duplicates",
		"  1: 100 bytes, 2026-01-01 00:00:00, MD5 abc",
		"  2: 100 bytes, 2026-01-02 00:00:00, MD5 abc",
	}, "\n")
	findings := parseDedupeList(output, "/library")
	if len(findings) != 3 {
		t.Fatalf("expected 3 individually selectable findings, got %#v", findings)
	}
	if findings[0].Path != "/library/Movies/Film" || findings[0].Scope != "/library/Movies" || findings[0].Count != 2 {
		t.Errorf("wrong folder finding: %#v", findings[0])
	}
	if findings[1].Path != "/library/Movies/Film/movie.mkv" || findings[1].Scope != "/library/Movies/Film" {
		t.Errorf("wrong file finding: %#v", findings[1])
	}
	if findings[2].Path != "/library/Movies/Other" || findings[2].Scope != "/library/Movies" {
		t.Errorf("wrong second folder: %#v", findings[2])
	}
}

func TestDedupeItemFiltersEscapeFolderName(t *testing.T) {
	finding := dedupeFinding{Kind: "merge", ItemType: "同名目录", Path: "/movies/Film (2024) {tmdb-42}", Scope: "/movies"}
	filters, err := dedupeItemFilters(finding)
	if err != nil || len(filters) != 4 || filters[1] != `+ /Film (2024) \{tmdb-42\}/**` {
		t.Fatalf("unsafe folder filter: %#v %v", filters, err)
	}
}

func TestEmptyDedupeDirsOnlyWithoutFileDescendants(t *testing.T) {
	listing := `[{"Path":"Movies","IsDir":true,"ModTime":"2026-10-01T00:00:00Z"},{"Path":"Movies/Film","IsDir":true,"ModTime":"2026-10-01T00:00:00Z"},{"Path":"Movies/Film/movie.mkv","IsDir":false},{"Path":"Movies/Empty","IsDir":true,"Metadata":{"btime":"2026-10-01T00:00:00Z"}}]`
	findings, err := emptyDedupeDirs(listing, "/library")
	if err != nil {
		t.Fatal(err)
	}
	if len(findings) != 1 || findings[0].Path != "/library/Movies/Empty" || findings[0].Kind != "empty" {
		t.Fatalf("unexpected empty directories: %#v", findings)
	}
}

func TestEmptyDedupeDirsIncludesEmptyParentChain(t *testing.T) {
	listing := `[{"Path":"Empty","IsDir":true,"ModTime":"2026-10-01T00:00:00Z"},{"Path":"Empty/Child","IsDir":true,"ModTime":"2026-10-01T00:00:00Z"}]`
	findings, err := emptyDedupeDirs(listing, "/")
	if err != nil {
		t.Fatal(err)
	}
	if len(findings) != 2 {
		t.Fatalf("expected both empty directories, got %#v", findings)
	}
}

func TestEmptyDedupeDirsIncludesYoungOrUnknownCopies(t *testing.T) {
	listing := `[{"Path":"Old","IsDir":true,"Metadata":{"btime":"2026-10-01T00:00:00Z"}},{"Path":"Old","IsDir":true,"Metadata":{"btime":"2026-10-18T00:00:00Z"}},{"Path":"Unknown","IsDir":true,"ModTime":"2000-01-01T00:00:00Z"},{"Path":"Old/Child","IsDir":true,"Metadata":{"btime":"2026-10-18T00:00:00Z"}}]`
	findings, err := emptyDedupeDirs(listing, "/movies")
	if err != nil || len(findings) != 3 {
		t.Fatalf("unexpected findings: %#v %v", findings, err)
	}
	if findings[0].Path != "/movies/Old" || findings[0].Count != 2 || findings[1].Path != "/movies/Old/Child" || findings[2].Path != "/movies/Unknown" {
		t.Fatalf("recent, unknown and duplicate empty directories should all be selectable: %#v", findings)
	}
}

func TestEmptyDedupeDirsListsSingleAndDuplicateFolders(t *testing.T) {
	listing := `[{"Path":"Single","IsDir":true,"ModTime":"2026-10-01T00:00:00Z"},{"Path":"Double","IsDir":true,"ModTime":"2026-10-01T00:00:00Z"},{"Path":"Double","IsDir":true,"ModTime":"2026-10-02T00:00:00Z"}]`
	findings, err := emptyDedupeDirs(listing, "/movies")
	if err != nil || len(findings) != 2 || findings[0].Count != 2 || findings[1].Count != 1 {
		t.Fatalf("expected empty single and duplicate folders: %#v %v", findings, err)
	}
}
