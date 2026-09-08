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
// verdict. The table lists only the rows that moved, plus the total, so a
// comment covering several modules stays short.
func WriteMarkdown(w io.Writer, name string, report *Report, kind Kind) error {
	var b strings.Builder

	fmt.Fprintf(&b, "%s\n#### `%s`\n\n%s\n\n", markdownMarker(report), name, markdownSummary(report, kind))
	fmt.Fprintf(&b, "| %s | Coverage | %s | Change |\n| --- | ---: | ---: | --- |\n",
		capitalize(kind.Unit), referenceColumn(report))
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
func markdownSummary(report *Report, kind Kind) string {
	if report.Total.Status == StatusNew {
		return fmt.Sprintf("No baseline, so nothing to compare. Total %s is %.1f%%.", kind.Name, report.Total.Percent)
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

	total := fmt.Sprintf("Total %s is %.1f%% (%+.1f against %s).",
		kind.Name, report.Total.Percent, report.Total.Percent-report.Total.Reference, referenceName(report))
	if len(parts) == 0 {
		if comparedAgainstBase(report) {
			return fmt.Sprintf("No %s moved against %s. %s", kind.Unit, referenceName(report), total)
		}
		return fmt.Sprintf("Every %s holds at its floor. %s", kind.Unit, total)
	}
	return fmt.Sprintf("%s: %s. %s", capitalize(kind.Units), strings.Join(parts, ", "), total)
}

func markdownRow(result Result) string {
	percent := fmt.Sprintf("%.1f%%", result.Percent)
	reference := fmt.Sprintf("%.1f%%", result.Reference)
	change := ""

	switch result.Status {
	case StatusNew:
		reference = ""
		change = "new"
	case StatusRemoved:
		percent = ""
		change = "removed"
	case StatusRegressed:
		change = fmt.Sprintf("**regressed by %.1f**", result.Reference-result.Percent)
	case StatusImproved:
		change = fmt.Sprintf("+%.1f", result.Percent-result.Reference)
	}

	return fmt.Sprintf("| %s | %s | %s | %s |\n", result.Package, percent, reference, change)
}

func markdownTotalRow(result Result) string {
	if result.Status == StatusNew {
		return fmt.Sprintf("| **total** | **%.1f%%** | | |\n", result.Percent)
	}
	return fmt.Sprintf("| **total** | **%.1f%%** | %.1f%% | %+.1f |\n",
		result.Percent, result.Reference, result.Percent-result.Reference)
}

// comparedAgainstBase reports whether the report compares against a base
// commit's snapshot rather than the committed floors.
func comparedAgainstBase(report *Report) bool {
	return report.Reference != nil && report.Reference.Kind == ReferenceBase
}

// referenceColumn is the header of the column holding the reference values.
func referenceColumn(report *Report) string {
	if comparedAgainstBase(report) {
		return "Base"
	}
	return "Floor"
}

// referenceName names the reference in a sentence. Both summary sentences use
// it, so the two wordings cannot drift apart.
func referenceName(report *Report) string {
	if comparedAgainstBase(report) {
		return fmt.Sprintf("base `%s`", report.Reference.Label)
	}
	return "the baseline"
}
