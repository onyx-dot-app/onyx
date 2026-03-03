package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/glamour/styles"

	"github.com/charmbracelet/lipgloss"
)

// entryKind is the type of chat entry.
type entryKind int

const (
	entryUser entryKind = iota
	entryAssistant
	entryInfo
	entryError
	entryCitation
)

// chatEntry is a single rendered entry in the chat history.
type chatEntry struct {
	kind      entryKind
	content   string   // raw content (for assistant: the markdown source)
	rendered  string   // pre-rendered output
	citations []string // citation lines (for citation entries)
}

// viewport manages the chat display.
type viewport struct {
	entries      []chatEntry
	width        int
	streaming    bool
	streamBuf    string
	showSources  bool
	renderer     *glamour.TermRenderer
	sessionItems []sessionItem // for session picker
	pickerActive bool
	pickerIndex  int
	scrollOffset int // lines scrolled up from bottom (0 = pinned to bottom)
}

type sessionItem struct {
	id    string
	label string
}

// newMarkdownRenderer creates a Glamour renderer with zero left margin.
func newMarkdownRenderer(width int) *glamour.TermRenderer {
	style := styles.DarkStyleConfig
	zero := uint(0)
	style.Document.Margin = &zero
	r, _ := glamour.NewTermRenderer(
		glamour.WithStyles(style),
		glamour.WithWordWrap(width-4),
	)
	return r
}

func newViewport(width int) *viewport {
	return &viewport{
		width:    width,
		renderer: newMarkdownRenderer(width),
	}
}

func (v *viewport) addSplash(height int) {
	splash := renderSplash(v.width, height)
	v.entries = append(v.entries, chatEntry{
		kind:     entryInfo,
		rendered: splash,
	})
}

func (v *viewport) setWidth(w int) {
	v.width = w
	v.renderer = newMarkdownRenderer(w)
}

func (v *viewport) addUserMessage(msg string) {
	rendered := "\n" + userPrefixStyle.Render("❯ ") + msg
	v.entries = append(v.entries, chatEntry{
		kind:     entryUser,
		content:  msg,
		rendered: rendered,
	})
}

func (v *viewport) startAssistant() {
	v.streaming = true
	v.streamBuf = ""
	// Add a blank-line spacer entry before the assistant message
	v.entries = append(v.entries, chatEntry{kind: entryInfo, rendered: ""})
}

func (v *viewport) appendToken(token string) {
	v.streamBuf += token
	v.scrollOffset = 0 // auto-scroll to bottom on new content
}

func (v *viewport) finishAssistant() {
	if v.streamBuf == "" {
		v.streaming = false
		return
	}

	// Render markdown with Glamour (zero left margin style)
	rendered := v.renderMarkdown(v.streamBuf)
	rendered = strings.TrimLeft(rendered, "\n")
	rendered = strings.TrimRight(rendered, "\n")
	lines := strings.Split(rendered, "\n")
	// Prefix first line with dot, indent continuation lines
	if len(lines) > 0 {
		lines[0] = assistantDot + " " + lines[0]
		for i := 1; i < len(lines); i++ {
			lines[i] = "  " + lines[i]
		}
	}
	rendered = strings.Join(lines, "\n")

	v.entries = append(v.entries, chatEntry{
		kind:     entryAssistant,
		content:  v.streamBuf,
		rendered: rendered,
	})
	v.streaming = false
	v.streamBuf = ""
}

func (v *viewport) renderMarkdown(md string) string {
	if v.renderer == nil {
		return md
	}
	out, err := v.renderer.Render(md)
	if err != nil {
		return md
	}
	return out
}

func (v *viewport) addInfo(msg string) {
	rendered := statusMsgStyle.Render("● " + msg)
	v.entries = append(v.entries, chatEntry{
		kind:     entryInfo,
		content:  msg,
		rendered: rendered,
	})
}

func (v *viewport) addError(msg string) {
	rendered := errorStyle.Render("Error: ") + msg
	v.entries = append(v.entries, chatEntry{
		kind:     entryError,
		content:  msg,
		rendered: rendered,
	})
}

func (v *viewport) addCitations(citations map[int]string) {
	if len(citations) == 0 {
		return
	}
	var parts []string
	for num := 1; num <= len(citations)+100; num++ {
		if docID, ok := citations[num]; ok {
			parts = append(parts, fmt.Sprintf("[%d] %s", num, docID))
		}
		if len(parts) == len(citations) {
			break
		}
	}
	text := fmt.Sprintf("Sources (%d): %s", len(citations), strings.Join(parts, "  "))
	var citLines []string
	citLines = append(citLines, text)

	v.entries = append(v.entries, chatEntry{
		kind:      entryCitation,
		content:   text,
		rendered:  citationStyle.Render("● "+text),
		citations: citLines,
	})
}

func (v *viewport) showSessionPicker(items []sessionItem) {
	v.sessionItems = items
	v.pickerActive = true
	v.pickerIndex = 0
}

func (v *viewport) scrollUp(n int) {
	v.scrollOffset += n
	// Clamped in view() since we need to know total content height
}

func (v *viewport) scrollDown(n int) {
	v.scrollOffset -= n
	if v.scrollOffset < 0 {
		v.scrollOffset = 0
	}
}

func (v *viewport) scrollToBottom() {
	v.scrollOffset = 0
}

func (v *viewport) clearAll() {
	v.entries = nil
	v.streaming = false
	v.streamBuf = ""
	v.sessionItems = nil
	v.pickerActive = false
	v.scrollOffset = 0
}

func (v *viewport) clearDisplay() {
	v.entries = nil
	v.scrollOffset = 0
}

// view renders the full viewport content.
func (v *viewport) view(height int) string {
	var lines []string

	for _, e := range v.entries {
		if e.kind == entryCitation && !v.showSources {
			continue
		}
		lines = append(lines, e.rendered)
	}

	// Streaming buffer (plain text, not markdown)
	if v.streaming && v.streamBuf != "" {
		bufLines := strings.Split(v.streamBuf, "\n")
		if len(bufLines) > 0 {
			bufLines[0] = assistantDot + " " + bufLines[0]
			for i := 1; i < len(bufLines); i++ {
				bufLines[i] = "  " + bufLines[i]
			}
		}
		lines = append(lines, strings.Join(bufLines, "\n"))
	} else if v.streaming {
		lines = append(lines, assistantDot+" ")
	}

	// Session picker
	if v.pickerActive && len(v.sessionItems) > 0 {
		lines = append(lines, "")
		for i, item := range v.sessionItems {
			prefix := "  "
			if i == v.pickerIndex {
				prefix = lipgloss.NewStyle().Foreground(accentColor).Render("> ")
			}
			lines = append(lines, prefix+item.label)
		}
		lines = append(lines, "")
	}

	content := strings.Join(lines, "\n")
	contentLines := strings.Split(content, "\n")
	total := len(contentLines)

	// Clamp scroll offset
	maxScroll := total - height
	if maxScroll < 0 {
		maxScroll = 0
	}
	if v.scrollOffset > maxScroll {
		v.scrollOffset = maxScroll
	}

	if total <= height {
		// Content fits — pad with empty lines at top to push content down
		padding := make([]string, height-total)
		for i := range padding {
			padding[i] = ""
		}
		contentLines = append(padding, contentLines...)
	} else {
		// Show a window: end is (total - scrollOffset), start is (end - height)
		end := total - v.scrollOffset
		start := end - height
		if start < 0 {
			start = 0
		}
		contentLines = contentLines[start:end]
	}

	return strings.Join(contentLines, "\n")
}

