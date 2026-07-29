// Package markdown renders CommonMark/GFM markdown into ANSI-styled text for
// terminal display. It walks the goldmark AST directly and deliberately avoids
// heavier renderer stacks (syntax-highlighting lexers, HTML sanitizers) to
// keep the binary small.
package markdown

import (
	"strings"

	"github.com/charmbracelet/x/ansi"
	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/extension"
	"github.com/yuin/goldmark/parser"
	"github.com/yuin/goldmark/text"
)

// mdParser is shared by all renderers: parsing is width-independent, and the
// parser carries no state between Parse calls. Construction is done once so
// NewRenderer stays cheap — the TUI rebuilds renderers on every resize.
var mdParser parser.Parser = goldmark.New(goldmark.WithExtensions(extension.GFM)).Parser()

// Renderer converts markdown source into ANSI-styled text wrapped at a fixed
// display-column width. Every output line is guaranteed to have display width
// at most the configured width (the chat viewport counts terminal rows by
// splitting on newlines, so an overflowing line would desync its scroll math).
type Renderer struct {
	width int
}

// NewRenderer creates a renderer that wraps output at the given width. The
// width is never raised: producing lines wider than the caller's budget would
// make the terminal soft-wrap them and desync the viewport's row accounting.
func NewRenderer(width int) *Renderer {
	if width < 1 {
		width = 1
	}
	return &Renderer{width: width}
}

// Render converts md into styled, width-wrapped terminal output. It never
// fails on partial or malformed markdown (an unterminated code fence
// mid-stream parses as a code block to EOF per CommonMark); if rendering
// panics due to a bug, the raw source is returned instead so the chat
// viewport always has something to display.
func (r *Renderer) Render(md string) (out string) {
	defer func() {
		if recover() != nil {
			out = md
		}
	}()
	source := []byte(md)
	doc := mdParser.Parse(text.NewReader(source))
	joined := strings.Join(renderBlocks(source, doc, r.width), "\n\n")

	// Safety net for the width invariant: pathological input (e.g. deeply
	// nested blockquotes) can stack prefixes past the budget; hard-wrap any
	// such line rather than let the terminal soft-wrap it.
	lines := strings.Split(joined, "\n")
	for i, line := range lines {
		if ansi.StringWidthWc(line) > r.width {
			lines[i] = ansi.HardwrapWc(line, r.width, true)
		}
	}
	return strings.Join(lines, "\n")
}
