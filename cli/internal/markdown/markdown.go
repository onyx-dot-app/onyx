// Package markdown renders CommonMark/GFM markdown into ANSI-styled text for
// terminal display. It replaces glamour with a small goldmark-AST walker so the
// binary does not carry syntax-highlighting lexers or an HTML sanitizer.
package markdown

import (
	"strings"

	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/extension"
	"github.com/yuin/goldmark/parser"
	"github.com/yuin/goldmark/text"
)

// minWidth is the narrowest wrap width the renderer will accept; below this,
// prefixed constructs (nested lists, blockquotes) run out of room.
const minWidth = 20

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

// NewRenderer creates a renderer that wraps output at the given width.
func NewRenderer(width int) *Renderer {
	if width < minWidth {
		width = minWidth
	}
	return &Renderer{width: width}
}

// Render converts md into styled, width-wrapped terminal output. It never
// fails on partial or malformed markdown (an unterminated code fence
// mid-stream parses as a code block to EOF per CommonMark); if rendering
// panics due to a bug, the raw source is returned instead, matching the
// fallback behavior the viewport had with glamour.
func (r *Renderer) Render(md string) (out string) {
	defer func() {
		if recover() != nil {
			out = md
		}
	}()
	source := []byte(md)
	doc := mdParser.Parse(text.NewReader(source))
	return strings.Join(renderBlocks(source, doc, r.width), "\n\n")
}
