package imgdiff

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// ScreenshotSummary describes a single screenshot that differs from the
// baseline. Unchanged screenshots are omitted, so consumers can iterate the
// list directly without filtering.
type ScreenshotSummary struct {
	Name        string  `json:"name"`
	Status      string  `json:"status"`
	DiffPercent float64 `json:"diff_percent"`
}

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

	// Screenshots lists the differing screenshots in the order produced by
	// CompareDirectories: changed first (by diff percent descending), then
	// added, then removed. The PR comment relies on this order to show the
	// most significant changes when it caps the number of rows.
	Screenshots []ScreenshotSummary `json:"screenshots"`
}

// BuildSummary computes a Summary from a slice of comparison results.
func BuildSummary(project string, results []Result) Summary {
	s := Summary{Project: project, Screenshots: []ScreenshotSummary{}}
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

		if r.Status != StatusUnchanged {
			s.Screenshots = append(s.Screenshots, ScreenshotSummary{
				Name:        r.Name,
				Status:      r.Status.String(),
				DiffPercent: r.DiffPercent,
			})
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
