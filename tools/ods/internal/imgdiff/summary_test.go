package imgdiff

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBuildSummary(t *testing.T) {
	tests := []struct {
		name    string
		results []Result
		want    Summary
	}{
		{
			name: "no results",
			want: Summary{Project: "admin"},
		},
		{
			name:    "only unchanged",
			results: []Result{{Status: StatusUnchanged}, {Status: StatusUnchanged}},
			want:    Summary{Project: "admin", Unchanged: 2, Total: 2},
		},
		{
			name: "every status",
			results: []Result{
				{Status: StatusChanged}, {Status: StatusChanged},
				{Status: StatusAdded}, {Status: StatusRemoved}, {Status: StatusUnchanged},
			},
			want: Summary{Project: "admin", Changed: 2, Added: 1, Removed: 1, Unchanged: 1, Total: 5, HasDifferences: true},
		},
		{
			name:    "a removal alone is a difference",
			results: []Result{{Status: StatusRemoved}},
			want:    Summary{Project: "admin", Removed: 1, Total: 1, HasDifferences: true},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := BuildSummary("admin", tt.results); got != tt.want {
				t.Fatalf("expected %+v, got %+v", tt.want, got)
			}
		})
	}
}

func TestWriteSummary_writesJSONIntoNewDirectories(t *testing.T) {
	path := filepath.Join(t.TempDir(), "out", "admin", "summary.json")
	summary := Summary{Project: "admin", Changed: 1, Total: 3, Unchanged: 2, HasDifferences: true}

	if err := WriteSummary(summary, path); err != nil {
		t.Fatalf("WriteSummary failed: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var got Summary
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("summary is not valid JSON: %v\n%s", err, data)
	}
	if got != summary {
		t.Fatalf("expected %+v, got %+v", summary, got)
	}
	if !strings.Contains(string(data), "\n  \"has_differences\": true") {
		t.Fatalf("expected indented snake_case keys, got:\n%s", data)
	}
}

func TestWriteSummary_reportsFailures(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "file")
	if err := os.WriteFile(file, nil, 0o644); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name string
		path string
		want string
	}{
		{"parent is a file", filepath.Join(file, "summary.json"), "failed to create directory for summary"},
		{"path is a directory", dir, "failed to write summary"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := WriteSummary(Summary{}, tt.path)
			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
		})
	}
}
