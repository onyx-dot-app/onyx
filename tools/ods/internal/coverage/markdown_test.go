package coverage

import (
	"strings"
	"testing"
)

func TestWriteMarkdown_showsEachStatus(t *testing.T) {
	profile := profileOf(map[string][2]int{
		"cmd":            {1, 4}, // 25%, below its 50 floor
		"internal/audit": {3, 4}, // 75%, above its 50 floor
		"internal/new":   {1, 2}, // no floor
	})
	baseline := &Baseline{
		Total:    50,
		Packages: map[string]float64{"cmd": 50, "internal/audit": 50, "internal/gone": 90},
	}

	var out strings.Builder
	if err := WriteMarkdown(&out, "tools/ods", Compare(profile, baseline, DefaultTolerance)); err != nil {
		t.Fatalf("failed to write the markdown: %v", err)
	}
	got := out.String()

	for _, want := range []string{
		MarkerChanged + "\n#### `tools/ods`",
		"Packages: 1 regressed, 1 improved, 1 new, 1 removed.",
		"| cmd | 25.0% | 50.0% | **regressed by 25.0** |",
		"| internal/audit | 75.0% | 50.0% | +25.0 |",
		"| internal/new | 50.0% |  | new |",
		"| internal/gone |  | 90.0% | removed |",
		"| **total** | **50.0%** | 50.0% | +0.0 |",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("expected %q in:\n%s", want, got)
		}
	}
}

// A package that holds at its floor is noise in a PR comment.
func TestWriteMarkdown_omitsUnchangedPackages(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}, "internal/audit": {3, 4}})
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50, "internal/audit": 50}}

	var out strings.Builder
	if err := WriteMarkdown(&out, "tools/ods", Compare(profile, baseline, DefaultTolerance)); err != nil {
		t.Fatalf("failed to write the markdown: %v", err)
	}

	if strings.Contains(out.String(), "| cmd |") {
		t.Errorf("expected the unchanged package omitted:\n%s", out.String())
	}
	if !strings.Contains(out.String(), "| internal/audit | 75.0% | 50.0% | +25.0 |") {
		t.Errorf("expected the improved package listed:\n%s", out.String())
	}
}

func TestWriteMarkdown_holdingBaselineSaysSo(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}})
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	var out strings.Builder
	if err := WriteMarkdown(&out, "tools/ods", Compare(profile, baseline, DefaultTolerance)); err != nil {
		t.Fatalf("failed to write the markdown: %v", err)
	}

	for _, want := range []string{MarkerUnchanged, "Every package holds at its floor."} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("expected %q in:\n%s", want, out.String())
		}
	}
}

func TestWriteMarkdown_noBaseline(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}})

	var out strings.Builder
	if err := WriteMarkdown(&out, "cli", Compare(profile, nil, DefaultTolerance)); err != nil {
		t.Fatalf("failed to write the markdown: %v", err)
	}

	for _, want := range []string{
		MarkerNoBaseline,
		"No baseline, so nothing to compare. Total coverage is 50.0%.",
		"| **total** | **50.0%** | | |",
	} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("expected %q in:\n%s", want, out.String())
		}
	}
}
