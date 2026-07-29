package markdown

import (
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/yuin/goldmark/ast"
	extast "github.com/yuin/goldmark/extension/ast"
)

// inlineAttrs is the merged set of inline styles active at a point in the
// walk. Each leaf text node is rendered once with the fully merged style;
// nesting independently-styled spans would let an inner span's SGR reset
// clobber the still-open outer style.
type inlineAttrs struct {
	bold   bool
	italic bool
	strike bool
	code   bool
	link   bool
}

func (a inlineAttrs) style() lipgloss.Style {
	s := lipgloss.NewStyle()
	switch {
	case a.code:
		s = s.Foreground(codeColor)
	case a.link:
		s = s.Foreground(accentColor).Underline(true)
	default:
		s = s.Foreground(textColor)
	}
	if a.bold {
		s = s.Bold(true)
	}
	if a.italic {
		s = s.Italic(true)
	}
	if a.strike {
		s = s.Strikethrough(true)
	}
	return s
}

// renderInlines renders the inline children of node with the given attrs.
func renderInlines(source []byte, node ast.Node, attrs inlineAttrs) string {
	var b strings.Builder
	for c := node.FirstChild(); c != nil; c = c.NextSibling() {
		b.WriteString(renderInline(source, c, attrs))
	}
	return b.String()
}

func renderInline(source []byte, node ast.Node, attrs inlineAttrs) string {
	switch n := node.(type) {
	case *ast.Text:
		out := attrs.style().Render(string(n.Segment.Value(source)))
		if n.HardLineBreak() {
			return out + "\n"
		}
		if n.SoftLineBreak() {
			return out + " "
		}
		return out
	case *ast.String:
		return attrs.style().Render(string(n.Value))
	case *ast.Emphasis:
		if n.Level >= 2 {
			attrs.bold = true
		} else {
			attrs.italic = true
		}
		return renderInlines(source, n, attrs)
	case *extast.Strikethrough:
		attrs.strike = true
		return renderInlines(source, n, attrs)
	case *ast.CodeSpan:
		attrs.code = true
		return renderInlines(source, n, attrs)
	case *ast.Link:
		attrs.link = true
		label := renderInlines(source, n, attrs)
		dest := string(n.Destination)
		if dest == "" || strings.TrimSpace(plainText(source, n)) == dest {
			return label
		}
		return label + dimStyle.Render(" ("+dest+")")
	case *ast.AutoLink:
		return inlineAttrs{link: true}.style().Render(string(n.Label(source)))
	case *ast.Image:
		alt := strings.TrimSpace(plainText(source, n))
		if alt == "" {
			alt = string(n.Destination)
		}
		return dimStyle.Render("[image: " + alt + "]")
	case *ast.RawHTML:
		var b strings.Builder
		for i := 0; i < n.Segments.Len(); i++ {
			seg := n.Segments.At(i)
			b.Write(seg.Value(source))
		}
		return dimStyle.Render(b.String())
	case *extast.TaskCheckBox:
		if n.IsChecked {
			return bulletStyle.Render("☑ ")
		}
		return dimStyle.Render("☐ ")
	default:
		return renderInlines(source, n, attrs)
	}
}

// plainText extracts the unstyled text content of a node's subtree.
func plainText(source []byte, node ast.Node) string {
	var b strings.Builder
	for c := node.FirstChild(); c != nil; c = c.NextSibling() {
		switch n := c.(type) {
		case *ast.Text:
			b.Write(n.Segment.Value(source))
			if n.SoftLineBreak() || n.HardLineBreak() {
				b.WriteByte(' ')
			}
		case *ast.String:
			b.Write(n.Value)
		default:
			b.WriteString(plainText(source, c))
		}
	}
	return b.String()
}
