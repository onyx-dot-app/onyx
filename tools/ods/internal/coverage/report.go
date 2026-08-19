package coverage

import (
	"fmt"
	"io"
	"strings"
	"text/tabwriter"
)

// WriteReport renders a report as an aligned table. Packages with no floor yet
// show a blank floor column rather than a misleading zero.
func WriteReport(w io.Writer, report *Report) error {
	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)

	if _, err := fmt.Fprintln(tw, "PACKAGE\tCOVERAGE\tFLOOR\t"); err != nil {
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
	if err := writeRow(tw, report.Total); err != nil {
		return err
	}

	return tw.Flush()
}

func writeRow(w io.Writer, result Result) error {
	percent := fmt.Sprintf("%.1f%%", result.Percent)
	floor := fmt.Sprintf("%.1f%%", result.Floor)
	note := ""

	switch result.Status {
	case StatusNew:
		floor = "-"
		note = "new"
	case StatusRemoved:
		percent = "-"
		note = "removed"
	case StatusRegressed:
		note = fmt.Sprintf("REGRESSED by %.1f", result.Floor-result.Percent)
	case StatusImproved:
		note = fmt.Sprintf("+%.1f", result.Percent-result.Floor)
	}

	_, err := fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", result.Package, percent, floor, note)
	return err
}
