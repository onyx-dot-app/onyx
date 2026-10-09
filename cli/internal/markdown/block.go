package markdown

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/x/ansi"
	"github.com/yuin/goldmark/ast"
	extast "github.com/yuin/goldmark/extension/ast"
)

// renderBlocks renders each child block of node at the given wrap width.
func renderBlocks(source []byte, node ast.Node, width int) []string {
	var blocks []string
	for c := node.FirstChild(); c != nil; c = c.NextSibling() {
		if s, ok := renderBlock(source, c, width); ok {
			blocks = append(blocks, s)
		}
	}
	return blocks
}

func renderBlock(source []byte, node ast.Node, width int) (string, bool) {
	switch n := node.(type) {
	case *ast.Heading:
		text := strings.TrimSpace(plainText(source, n))
		if text == "" {
			return "", false
		}
		return styleLines(ansi.WrapWc(text, width, ""), headingStyle(n.Level)), true
	case *ast.Paragraph, *ast.TextBlock:
		content := renderInlines(source, n, inlineAttrs{})
		if strings.TrimSpace(ansi.Strip(content)) == "" {
			return "", false
		}
		return ansi.WrapWc(content, width, ""), true
	case *ast.Blockquote:
		return renderBlockquote(source, n, width)
	case *ast.List:
		return renderList(source, n, width)
	case *ast.FencedCodeBlock:
		lang := string(n.Language(source))
		return renderCode(source, n, lang, width), true
	case *ast.CodeBlock:
		return renderCode(source, n, "", width), true
	case *ast.ThematicBreak:
		return dimStyle.Render(strings.Repeat("─", width)), true
	case *ast.HTMLBlock:
		return renderHTMLBlock(source, n, width)
	case *extast.Table:
		return renderTable(source, n, width), true
	default:
		// Unknown block kind: render its block children if any, else fall
		// back to its inline content.
		if inner := renderBlocks(source, n, width); len(inner) > 0 {
			return strings.Join(inner, "\n\n"), true
		}
		content := renderInlines(source, n, inlineAttrs{})
		if strings.TrimSpace(ansi.Strip(content)) == "" {
			return "", false
		}
		return ansi.WrapWc(content, width, ""), true
	}
}

func renderBlockquote(source []byte, n *ast.Blockquote, width int) (string, bool) {
	bar := dimStyle.Render("│ ")
	inner := renderBlocks(source, n, innerWidth(width, 2))
	if len(inner) == 0 {
		return "", false
	}
	return prefixLines(strings.Join(inner, "\n\n"), bar, bar), true
}

func renderList(source []byte, n *ast.List, width int) (string, bool) {
	num := n.Start
	if num == 0 {
		num = 1
	}
	sep := "\n\n"
	if n.IsTight {
		sep = "\n"
	}
	var items []string
	for it := n.FirstChild(); it != nil; it = it.NextSibling() {
		var marker string
		switch {
		case isTaskItem(it):
			// The checkbox glyph rendered inline acts as the marker.
		case n.IsOrdered():
			marker = fmt.Sprintf("%d. ", num)
			num++
		default:
			marker = "• "
		}
		mw := ansi.StringWidthWc(marker)
		body := strings.Join(renderBlocks(source, it, innerWidth(width, mw)), sep)
		items = append(items, prefixLines(body, bulletStyle.Render(marker), strings.Repeat(" ", mw)))
	}
	if len(items) == 0 {
		return "", false
	}
	return strings.Join(items, sep), true
}

// isTaskItem reports whether a list item starts with a GFM task checkbox.
func isTaskItem(item ast.Node) bool {
	block := item.FirstChild()
	if block == nil {
		return false
	}
	_, ok := block.FirstChild().(*extast.TaskCheckBox)
	return ok
}

func renderCode(source []byte, n ast.Node, lang string, width int) string {
	bar := dimStyle.Render("│ ")
	budget := innerWidth(width, 2)
	var out []string
	if lang != "" {
		out = append(out, bar+dimStyle.Render(lang))
	}
	lines := n.Lines()
	rawLines := make([]string, 0, lines.Len())
	for i := 0; i < lines.Len(); i++ {
		seg := lines.At(i)
		line := strings.TrimRight(string(seg.Value(source)), "\r\n")
		rawLines = append(rawLines, strings.ReplaceAll(line, "\t", "    "))
	}
	styled, ok := highlightLines(strings.Join(rawLines, "\n"), lang)
	if !ok {
		styled = make([]string, len(rawLines))
		for i, l := range rawLines {
			styled[i] = codeStyle.Render(l)
		}
	}
	for _, l := range styled {
		wrapped := ansi.HardwrapWc(l, budget, true)
		for _, w := range strings.Split(wrapped, "\n") {
			out = append(out, bar+w)
		}
	}
	return strings.Join(out, "\n")
}

func renderHTMLBlock(source []byte, n *ast.HTMLBlock, width int) (string, bool) {
	var out []string
	lines := n.Lines()
	for i := 0; i < lines.Len(); i++ {
		seg := lines.At(i)
		raw := strings.TrimRight(string(seg.Value(source)), "\r\n")
		out = append(out, styleLines(ansi.HardwrapWc(raw, width, true), dimStyle))
	}
	if n.HasClosure() {
		raw := strings.TrimRight(string(n.ClosureLine.Value(source)), "\r\n")
		out = append(out, styleLines(ansi.HardwrapWc(raw, width, true), dimStyle))
	}
	if len(out) == 0 {
		return "", false
	}
	return strings.Join(out, "\n"), true
}

// innerWidth is the wrap budget left inside a prefixed block. It never drops
// below 1: x/ansi wrappers return input unwrapped for limits < 1, which would
// produce arbitrarily long lines.
func innerWidth(width, prefix int) int {
	if w := width - prefix; w > 0 {
		return w
	}
	return 1
}

// prefixLines prepends first to the first line of s and rest to every other.
func prefixLines(s, first, rest string) string {
	lines := strings.Split(s, "\n")
	for i := range lines {
		if i == 0 {
			lines[i] = first + lines[i]
		} else {
			lines[i] = rest + lines[i]
		}
	}
	return strings.Join(lines, "\n")
}

// styleLines applies style to each line of s independently so that no SGR
// state leaks across newlines (the viewport indents continuation lines).
func styleLines(s string, style interface{ Render(...string) string }) string {
	lines := strings.Split(s, "\n")
	for i := range lines {
		lines[i] = style.Render(lines[i])
	}
	return strings.Join(lines, "\n")
}
