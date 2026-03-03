package tui

import (
	"fmt"
	"sort"
	"strings"

	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/glamour/styles"

	"github.com/charmbracelet/lipgloss"
)

// entryKind is the type of chat entry.
type entryKind int

const (
	entryUser entryKind = iota
	entryAgent
	entryInfo
	entryError
	entryCitation
)

// chatEntry is a single rendered entry in the chat history.
type chatEntry struct {
	kind      entryKind
	content   string   // raw content (for agent: the markdown source)
	rendered  string   // pre-rendered output
	citations []string // citation lines (for citation entries)
}

// pickerKind distinguishes what the picker is selecting.
type pickerKind int

const (
	pickerSession pickerKind = iota
	pickerAgent
)

// pickerItem is a selectable item in the picker.
type pickerItem struct {
	id    string
	label string
}

// viewport manages the chat display.
type viewport struct {
	entries      []chatEntry
	width        int
	streaming    bool
	streamBuf    string
	showSources  bool
	renderer     *glamour.TermRenderer
	pickerItems  []pickerItem
	pickerActive bool
	pickerIndex  int
	pickerType   pickerKind
	scrollOffset int // lines scrolled up from bottom (0 = pinned to bottom)
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

func (v *viewport) startAgent() {
	v.streaming = true
	v.streamBuf = ""
	// Add a blank-line spacer entry before the agent message
	v.entries = append(v.entries, chatEntry{kind: entryInfo, rendered: ""})
}

func (v *viewport) appendToken(token string) {
	v.streamBuf += token
	v.scrollOffset = 0 // auto-scroll to bottom on new content
}

func (v *viewport) finishAgent() {
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
		lines[0] = agentDot + " " + lines[0]
		for i := 1; i < len(lines); i++ {
			lines[i] = "  " + lines[i]
		}
	}
	rendered = strings.Join(lines, "\n")

	v.entries = append(v.entries, chatEntry{
		kind:     entryAgent,
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
	rendered := infoStyle.Render("● " + msg)
	v.entries = append(v.entries, chatEntry{
		kind:     entryInfo,
		content:  msg,
		rendered: rendered,
	})
}

func (v *viewport) addWarning(msg string) {
	rendered := warnStyle.Render("● " + msg)
	v.entries = append(v.entries, chatEntry{
		kind:     entryError,
		content:  msg,
		rendered: rendered,
	})
}

func (v *viewport) addError(msg string) {
	rendered := errorStyle.Render("● Error: ") + msg
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
	keys := make([]int, 0, len(citations))
	for k := range citations {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	var parts []string
	for _, num := range keys {
		parts = append(parts, fmt.Sprintf("[%d] %s", num, citations[num]))
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

func (v *viewport) showPicker(kind pickerKind, items []pickerItem) {
	v.pickerItems = items
	v.pickerType = kind
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

func (v *viewport) clearAll() {
	v.entries = nil
	v.streaming = false
	v.streamBuf = ""
	v.pickerItems = nil
	v.pickerActive = false
	v.scrollOffset = 0
}

func (v *viewport) clearDisplay() {
	v.entries = nil
	v.scrollOffset = 0
}

// pickerTitle returns a title for the current picker kind.
func (v *viewport) pickerTitle() string {
	switch v.pickerType {
	case pickerAgent:
		return "Select Agent"
	case pickerSession:
		return "Resume Session"
	default:
		return "Select"
	}
}

// renderPicker renders the picker as a bordered overlay.
func (v *viewport) renderPicker(width, height int) string {
	title := v.pickerTitle()

	// Determine picker dimensions
	maxItems := len(v.pickerItems)
	panelWidth := width - 4
	if panelWidth < 30 {
		panelWidth = 30
	}
	if panelWidth > 70 {
		panelWidth = 70
	}
	innerWidth := panelWidth - 4 // border + padding

	// Visible window of items (scroll if too many)
	maxVisible := height - 6 // room for border, title, hint
	if maxVisible < 3 {
		maxVisible = 3
	}
	if maxVisible > maxItems {
		maxVisible = maxItems
	}

	// Calculate scroll window around current index
	startIdx := 0
	if v.pickerIndex >= maxVisible {
		startIdx = v.pickerIndex - maxVisible + 1
	}
	endIdx := startIdx + maxVisible
	if endIdx > maxItems {
		endIdx = maxItems
		startIdx = endIdx - maxVisible
		if startIdx < 0 {
			startIdx = 0
		}
	}

	var itemLines []string
	for i := startIdx; i < endIdx; i++ {
		item := v.pickerItems[i]
		label := item.label
		if len(label) > innerWidth-4 {
			label = label[:innerWidth-7] + "..."
		}
		if i == v.pickerIndex {
			line := lipgloss.NewStyle().Foreground(accentColor).Bold(true).Render("> " + label)
			itemLines = append(itemLines, line)
		} else {
			itemLines = append(itemLines, "  "+label)
		}
	}

	hint := lipgloss.NewStyle().Foreground(dimColor).Render("↑↓ navigate • enter select • esc cancel")

	body := strings.Join(itemLines, "\n") + "\n\n" + hint

	panel := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(accentColor).
		Padding(1, 2).
		Width(panelWidth).
		Render(body)

	titleRendered := lipgloss.NewStyle().
		Foreground(accentColor).
		Bold(true).
		Render(" " + title + " ")

	// Place title on top border
	panelLines := strings.Split(panel, "\n")
	if len(panelLines) > 0 {
		border := panelLines[0]
		runes := []rune(border)
		if len(runes) > 4 {
			// Insert title after the 2nd rune of the border
			titleRunes := []rune(titleRendered)
			panelLines[0] = string(runes[:2]) + string(titleRunes) + string(runes[2:])
		}
	}
	panel = strings.Join(panelLines, "\n")

	// Center the panel in the viewport
	return lipgloss.Place(width, height, lipgloss.Center, lipgloss.Center, panel)
}

// view renders the full viewport content.
func (v *viewport) view(height int) string {
	// If picker is active, render it as an overlay
	if v.pickerActive && len(v.pickerItems) > 0 {
		return v.renderPicker(v.width, height)
	}

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
			bufLines[0] = agentDot + " " + bufLines[0]
			for i := 1; i < len(bufLines); i++ {
				bufLines[i] = "  " + bufLines[i]
			}
		}
		lines = append(lines, strings.Join(bufLines, "\n"))
	} else if v.streaming {
		lines = append(lines, agentDot+" ")
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

