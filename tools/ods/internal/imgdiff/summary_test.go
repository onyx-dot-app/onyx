package imgdiff

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestBuildSummary_Screenshots(t *testing.T) {
	results := []Result{
		{Name: "b.png", Status: StatusChanged, DiffPercent: 9.5},
		{Name: "a.png", Status: StatusChanged, DiffPercent: 1.25},
		{Name: "c.png", Status: StatusAdded},
		{Name: "d.png", Status: StatusRemoved},
		{Name: "e.png", Status: StatusUnchanged},
	}

	summary := BuildSummary("admin", results)

	if summary.Changed != 2 || summary.Added != 1 || summary.Removed != 1 || summary.Unchanged != 1 {
		t.Errorf("unexpected counts: %+v", summary)
	}
	if summary.Total != 5 {
		t.Errorf("Total = %d, want 5", summary.Total)
	}
	if !summary.HasDifferences {
		t.Error("HasDifferences = false, want true")
	}

	// Unchanged entries are omitted; the input order is preserved so the PR
	// comment shows the largest diffs first when it caps rows.
	want := []ScreenshotSummary{
		{Name: "b.png", Status: "changed", DiffPercent: 9.5},
		{Name: "a.png", Status: "changed", DiffPercent: 1.25},
		{Name: "c.png", Status: "added"},
		{Name: "d.png", Status: "removed"},
	}

	if len(summary.Screenshots) != len(want) {
		t.Fatalf("got %d screenshots, want %d: %+v", len(summary.Screenshots), len(want), summary.Screenshots)
	}
	for i, w := range want {
		if summary.Screenshots[i] != w {
			t.Errorf("screenshot %d = %+v, want %+v", i, summary.Screenshots[i], w)
		}
	}
}

func TestBuildSummary_NoResults(t *testing.T) {
	summary := BuildSummary("admin", nil)

	if summary.HasDifferences {
		t.Error("HasDifferences = true, want false")
	}
	if summary.Total != 0 {
		t.Errorf("Total = %d, want 0", summary.Total)
	}

	// The comment job iterates this array with jq, so it must serialize as []
	// rather than null.
	data, err := json.Marshal(summary)
	if err != nil {
		t.Fatalf("failed to marshal summary: %v", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("failed to unmarshal summary: %v", err)
	}
	screenshots, ok := decoded["screenshots"].([]any)
	if !ok {
		t.Fatalf("screenshots is not a JSON array: %v", decoded["screenshots"])
	}
	if len(screenshots) != 0 {
		t.Errorf("got %d screenshots, want 0", len(screenshots))
	}
}

func TestWriteSummary_RoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "summary.json")

	want := BuildSummary("exclusive", []Result{
		{Name: "a.png", Status: StatusChanged, DiffPercent: 3.5},
	})
	if err := WriteSummary(want, path); err != nil {
		t.Fatalf("WriteSummary failed: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read summary: %v", err)
	}
	var got Summary
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("failed to unmarshal summary: %v", err)
	}

	if got.Project != "exclusive" || got.Changed != 1 || !got.HasDifferences {
		t.Errorf("unexpected summary: %+v", got)
	}
	if len(got.Screenshots) != 1 || got.Screenshots[0].Name != "a.png" {
		t.Errorf("unexpected screenshots: %+v", got.Screenshots)
	}
	if got.Screenshots[0].DiffPercent != 3.5 {
		t.Errorf("DiffPercent = %v, want 3.5", got.Screenshots[0].DiffPercent)
	}
}
