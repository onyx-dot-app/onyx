package coverage

import (
	"fmt"
	"io"
	"strings"
)

// Markers open a markdown report so a script can tell, without parsing the
// table, whether the module is worth a reader's attention.
const (
	MarkerChanged    = "<!-- ods-coverage: changed -->"
	MarkerUnchanged  = "<!-- ods-coverage: unchanged -->"
	MarkerNoBaseline = "<!-- ods-coverage: no-baseline -->"
)

// WriteMarkdown renders a report as a GitHub-flavored markdown section for a
// PR comment or job summary. A marker line comes first, then a one-line
// verdict. The table lists only the packages that moved, plus the total, so a
// comment covering several modules stays short.
func WriteMarkdown(w io.Writer, name string, report *Report) error {
	var b strings.Builder

	fmt.Fprintf(&b, "%s\n#### `%s`\n\n%s\n\n", markdownMarker(report), name, markdownSummary(report))
	b.WriteString("| Package | Coverage | Floor | Change |\n| --- | ---: | ---: | --- |\n")
	for _, pkg := range report.Packages {
		if pkg.Status != StatusOK {
			b.WriteString(markdownRow(pkg))
		}
	}
	b.WriteString(markdownTotalRow(report.Total))

	_, err := io.WriteString(w, b.String())
	return err
}

func markdownMarker(report *Report) string {
	switch {
	case report.Total.Status == StatusNew:
		return MarkerNoBaseline
	case report.Changed():
		return MarkerChanged
	default:
		return MarkerUnchanged
	}
}

// markdownSummary is the one line a reader needs: what moved, and the total.
func markdownSummary(report *Report) string {
	if report.Total.Status == StatusNew {
		return fmt.Sprintf("No baseline, so nothing to compare. Total coverage is %.1f%%.", report.Total.Percent)
	}

	counts := map[Status]int{}
	for _, pkg := range report.Packages {
		counts[pkg.Status]++
	}
	var parts []string
	for _, status := range []Status{StatusRegressed, StatusImproved, StatusNew, StatusRemoved} {
		if n := counts[status]; n > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", n, status))
		}
	}

	total := fmt.Sprintf("Total coverage is %.1f%% (%+.1f against the baseline).",
		report.Total.Percent, report.Total.Percent-report.Total.Floor)
	if len(parts) == 0 {
		return "Every package holds at its floor. " + total
	}
	return fmt.Sprintf("Packages: %s. %s", strings.Join(parts, ", "), total)
}

func markdownRow(result Result) string {
	percent := fmt.Sprintf("%.1f%%", result.Percent)
	floor := fmt.Sprintf("%.1f%%", result.Floor)
	change := ""

	switch result.Status {
	case StatusNew:
		floor = ""
		change = "new"
	case StatusRemoved:
		percent = ""
		change = "removed"
	case StatusRegressed:
		change = fmt.Sprintf("**regressed by %.1f**", result.Floor-result.Percent)
	case StatusImproved:
		change = fmt.Sprintf("+%.1f", result.Percent-result.Floor)
	}

	return fmt.Sprintf("| %s | %s | %s | %s |\n", result.Package, percent, floor, change)
}

func markdownTotalRow(result Result) string {
	if result.Status == StatusNew {
		return fmt.Sprintf("| **total** | **%.1f%%** | | |\n", result.Percent)
	}
	return fmt.Sprintf("| **total** | **%.1f%%** | %.1f%% | %+.1f |\n",
		result.Percent, result.Floor, result.Percent-result.Floor)
}
