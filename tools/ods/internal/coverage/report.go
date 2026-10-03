package coverage

import (
	"fmt"
	"io"
	"strings"
	"text/tabwriter"
)

// WriteReport renders a report as an aligned table. Rows with no reference
// value yet show a blank column rather than a misleading zero.
func WriteReport(w io.Writer, report *Report, kind Kind) error {
	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)

	if _, err := fmt.Fprintf(tw, "%s\tCOVERAGE\t%s\t\n",
		strings.ToUpper(kind.Unit), strings.ToUpper(referenceColumn(report))); err != nil {
		return err
	}
	for _, pkg := range report.Packages {
		if err := writeRow(tw, pkg); err != nil {
			return err
		}
	}
	if _, err := fmt.Fprint(tw, strings.Repeat("-", 8)+"\t"+strings.Repeat("-", 8)+"\t"+strings.Repeat("-", 8)+"\t\n"); err != nil {
		return err
	}
	if err := writeTotalRow(tw, report.Total); err != nil {
		return err
	}

	return tw.Flush()
}

func writeRow(w io.Writer, result Result) error {
	percent := fmt.Sprintf("%.1f%%", result.Percent)
	reference := fmt.Sprintf("%.1f%%", result.Reference)
	note := ""

	switch result.Status {
	case StatusNew:
		reference = "-"
		note = "new"
	case StatusRemoved:
		percent = "-"
		note = "removed"
	case StatusRegressed:
		note = fmt.Sprintf("REGRESSED by %.1f", result.Reference-result.Percent)
	case StatusImproved:
		note = fmt.Sprintf("+%.1f", result.Percent-result.Reference)
	}

	_, err := fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", result.Package, percent, reference, note)
	return err
}

// writeTotalRow renders the module total. The total is not gated, so a drop
// is shown as a signed delta rather than a regression.
func writeTotalRow(w io.Writer, result Result) error {
	if result.Status == StatusNew {
		_, err := fmt.Fprintf(w, "%s\t%.1f%%\t-\t\n", result.Package, result.Percent)
		return err
	}
	_, err := fmt.Fprintf(w, "%s\t%.1f%%\t%.1f%%\t%+.1f\n",
		result.Package, result.Percent, result.Reference, result.Percent-result.Reference)
	return err
}
