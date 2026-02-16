package imgdiff

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// Summary holds aggregate comparison results in a JSON-friendly format.
// It is written alongside the HTML report so that CI pipelines can read it
// without parsing HTML.
type Summary struct {
	Project        string `json:"project"`
	Changed        int    `json:"changed"`
	Added          int    `json:"added"`
	Removed        int    `json:"removed"`
	Unchanged      int    `json:"unchanged"`
	Total          int    `json:"total"`
	HasDifferences bool   `json:"has_differences"`
}

// BuildSummary computes a Summary from a slice of comparison results.
func BuildSummary(project string, results []Result) Summary {
	s := Summary{Project: project}
	for _, r := range results {
		switch r.Status {
		case StatusChanged:
			s.Changed++
		case StatusAdded:
			s.Added++
		case StatusRemoved:
			s.Removed++
		case StatusUnchanged:
			s.Unchanged++
		}
	}
	s.Total = len(results)
	s.HasDifferences = s.Changed > 0 || s.Added > 0 || s.Removed > 0
	return s
}

// WriteSummary writes a Summary as pretty-printed JSON to the given path,
// creating parent directories as needed.
func WriteSummary(summary Summary, path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("failed to create directory for summary: %w", err)
	}

	data, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal summary: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write summary: %w", err)
	}

	return nil
}
