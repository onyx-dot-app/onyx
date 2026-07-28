package markdown

import (
	"strings"

	"github.com/charmbracelet/x/ansi"
	extast "github.com/yuin/goldmark/extension/ast"
)

// minColWidth is the narrowest a table column will be squeezed to before the
// table gives up fitting and relies on the final per-line truncation guard.
const minColWidth = 3

func renderTable(source []byte, t *extast.Table, width int) string {
	var rows [][]string
	headerRows := 0
	for r := t.FirstChild(); r != nil; r = r.NextSibling() {
		_, hdr := r.(*extast.TableHeader)
		var cells []string
		for c := r.FirstChild(); c != nil; c = c.NextSibling() {
			attrs := inlineAttrs{bold: hdr}
			content := strings.ReplaceAll(renderInlines(source, c, attrs), "\n", " ")
			cells = append(cells, content)
		}
		if hdr {
			headerRows++
		}
		rows = append(rows, cells)
	}
	if len(rows) == 0 {
		return ""
	}

	ncols := 0
	for _, r := range rows {
		if len(r) > ncols {
			ncols = len(r)
		}
	}
	colw := make([]int, ncols)
	for _, r := range rows {
		for i, c := range r {
			if w := ansi.StringWidthWc(c); w > colw[i] {
				colw[i] = w
			}
		}
	}
	for i := range colw {
		if colw[i] < minColWidth {
			colw[i] = minColWidth
		}
	}

	// Squeeze the widest columns until the table fits (or every column is at
	// its minimum; the per-line truncation below then keeps the width
	// invariant).
	total := func() int {
		t := 3 * (ncols - 1)
		for _, w := range colw {
			t += w
		}
		return t
	}
	for total() > width {
		widest := 0
		for i, w := range colw {
			if w > colw[widest] {
				widest = i
			}
		}
		if colw[widest] <= minColWidth {
			break
		}
		colw[widest]--
	}

	align := func(i int) extast.Alignment {
		if i < len(t.Alignments) {
			return t.Alignments[i]
		}
		return extast.AlignNone
	}

	sep := dimStyle.Render(" │ ")
	var out []string
	for ri, r := range rows {
		cells := make([]string, ncols)
		for i := range cells {
			var c string
			if i < len(r) {
				c = r[i]
			}
			cells[i] = padCell(c, colw[i], align(i))
		}
		out = append(out, ansi.TruncateWc(strings.Join(cells, sep), width, "…"))
		if ri == headerRows-1 {
			dashes := make([]string, ncols)
			for i, w := range colw {
				dashes[i] = strings.Repeat("─", w)
			}
			rule := dimStyle.Render(strings.Join(dashes, "─┼─"))
			out = append(out, ansi.TruncateWc(rule, width, "…"))
		}
	}
	return strings.Join(out, "\n")
}

func padCell(s string, w int, align extast.Alignment) string {
	s = ansi.TruncateWc(s, w, "…")
	gap := w - ansi.StringWidthWc(s)
	if gap <= 0 {
		return s
	}
	switch align {
	case extast.AlignRight:
		return strings.Repeat(" ", gap) + s
	case extast.AlignCenter:
		left := gap / 2
		return strings.Repeat(" ", left) + s + strings.Repeat(" ", gap-left)
	default:
		return s + strings.Repeat(" ", gap)
	}
}
