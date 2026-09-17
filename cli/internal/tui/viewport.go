package tui

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"charm.land/lipgloss/v2"

	"github.com/onyx-dot-app/onyx/cli/internal/markdown"
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
	kind     entryKind
	content  string // raw content (for agent: the markdown source)
	rendered string // pre-rendered output
}

// pickerKind distinguishes what the picker is selecting.
type pickerKind int

const (
	pickerSession pickerKind = iota
	pickerAgent
	pickerModel
)

// pickerItem is a selectable item in the picker. detail, when set, is
// right-aligned on the row (like a tabwriter column).
type pickerItem struct {
	id     string
	label  string
	detail string
}

// streamRenderInterval is the minimum time between markdown re-renders during streaming.
const streamRenderInterval = 100 * time.Millisecond

// viewport manages the chat display.
type viewport struct {
	entries      []chatEntry
	width        int
	streaming    bool
	streamBuf    string
	showSources  bool
	renderer     *markdown.Renderer
	pickerItems  []pickerItem
	pickerActive bool
	pickerIndex  int
	pickerType   pickerKind
	scrollOffset int // lines scrolled up from bottom (0 = pinned to bottom)

	// Progressive markdown rendering during streaming
	streamMarkdown bool   // feature flag: render markdown while streaming
	streamRendered string // cached rendered output during streaming
	lastRenderTime time.Time
	lastRenderLen  int // length of streamBuf at last render (skip if unchanged)
}

// newMarkdownRenderer creates a markdown renderer wrapping at width-4 to
// leave room for the agent-entry indent.
func newMarkdownRenderer(width int) *markdown.Renderer {
	return markdown.NewRenderer(width - 4)
}

func newViewport(width int, streamMarkdown bool) *viewport {
	return &viewport{
		width:          width,
		renderer:       newMarkdownRenderer(width),
		streamMarkdown: streamMarkdown,
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
	for i := range v.entries {
		if v.entries[i].kind == entryAgent && v.entries[i].content != "" {
			v.entries[i].rendered = v.renderAgentContent(v.entries[i].content)
		}
	}
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
	v.streamRendered = ""
	v.lastRenderLen = 0
	v.lastRenderTime = time.Time{}
	// Add a blank-line spacer entry before the agent message
	v.entries = append(v.entries, chatEntry{kind: entryInfo, rendered: ""})
}

func (v *viewport) appendToken(token string) {
	v.streamBuf += token

	if !v.streamMarkdown {
		return
	}

	now := time.Now()
	bufLen := len(v.streamBuf)
	if bufLen != v.lastRenderLen && now.Sub(v.lastRenderTime) >= streamRenderInterval {
		v.streamRendered = v.renderAgentContent(v.streamBuf)
		v.lastRenderTime = now
		v.lastRenderLen = bufLen
	}
}

func (v *viewport) finishAgent() {
	if v.streamBuf == "" {
		v.streaming = false
		// Remove the blank spacer entry added by startAgent()
		if len(v.entries) > 0 && v.entries[len(v.entries)-1].kind == entryInfo && v.entries[len(v.entries)-1].rendered == "" {
			v.entries = v.entries[:len(v.entries)-1]
		}
		return
	}

	rendered := v.renderAgentContent(v.streamBuf)

	v.entries = append(v.entries, chatEntry{
		kind:     entryAgent,
		content:  v.streamBuf,
		rendered: rendered,
	})
	v.streaming = false
	v.streamBuf = ""
	v.streamRendered = ""
	v.lastRenderLen = 0
}

func (v *viewport) renderAgentContent(content string) string {
	rendered := v.renderMarkdown(content)
	rendered = strings.TrimLeft(rendered, "\n")
	rendered = strings.TrimRight(rendered, "\n")
	lines := strings.Split(rendered, "\n")
	if len(lines) > 0 {
		lines[0] = agentDot + " " + lines[0]
		for i := 1; i < len(lines); i++ {
			lines[i] = "  " + lines[i]
		}
	}
	return strings.Join(lines, "\n")
}

func (v *viewport) renderMarkdown(md string) string {
	if v.renderer == nil {
		return md
	}
	return v.renderer.Render(md)
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

	v.entries = append(v.entries, chatEntry{
		kind:     entryCitation,
		content:  text,
		rendered: citationStyle.Render("● " + text),
	})
}

func (v *viewport) showPicker(kind pickerKind, items []pickerItem) {
	v.pickerItems = items
	v.pickerType = kind
	v.pickerActive = true
	v.pickerIndex = 0
}

func (v *viewport) scrollUp(n int, height int) {
	v.scrollOffset += n
	maxScroll := v.totalLines() - height
	if maxScroll < 0 {
		maxScroll = 0
	}
	if v.scrollOffset > maxScroll {
		v.scrollOffset = maxScroll
	}
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
	v.streaming = false
	v.streamBuf = ""
}

// pickerTitle returns a title for the current picker kind.
func (v *viewport) pickerTitle() string {
	switch v.pickerType {
	case pickerAgent:
		return "Select Agent"
	case pickerSession:
		return "Resume Session"
	case pickerModel:
		return "Select Model"
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

	// Computed over all items (not just the visible window) so the column
	// stays put while scrolling.
	detailCol := pickerDetailCol(v.pickerItems, innerWidth-4)

	var itemLines []string
	for i := startIdx; i < endIdx; i++ {
		item := v.pickerItems[i]
		label := formatPickerLabel(item, innerWidth-4, detailCol)
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

	// Build top border manually to avoid ANSI-corrupted rune slicing. Measure
	// the rendered panel instead of assuming its width — lipgloss box sizing
	// would put the replacement line off by one.
	panelLines := strings.Split(panel, "\n")
	panelTotalWidth := lipgloss.Width(panelLines[len(panelLines)-1])
	borderColor := lipgloss.NewStyle().Foreground(accentColor)
	titleWidth := lipgloss.Width(titleRendered)
	rightDashes := panelTotalWidth - 3 - titleWidth // total - "╭─" - "╮" - title
	if rightDashes < 0 {
		rightDashes = 0
	}
	topBorder := borderColor.Render("╭─") + titleRendered +
		borderColor.Render(strings.Repeat("─", rightDashes)+"╮")

	if len(panelLines) > 0 {
		panelLines[0] = topBorder
	}
	panel = strings.Join(panelLines, "\n")

	// Center the panel in the viewport
	return lipgloss.Place(width, height, lipgloss.Center, lipgloss.Center, panel)
}

// pickerDetailCol returns the column where the detail column starts, so
// details left-align across rows: two past the widest label, pulled back so
// the widest detail still fits in avail. Zero when no item has a detail.
func pickerDetailCol(items []pickerItem, avail int) int {
	maxLabel, maxDetail := 0, 0
	for _, it := range items {
		if it.detail == "" {
			continue
		}
		if w := len([]rune(it.label)); w > maxLabel {
			maxLabel = w
		}
		if w := len([]rune(it.detail)); w > maxDetail {
			maxDetail = w
		}
	}
	if maxDetail == 0 {
		return 0
	}
	col := maxLabel + 2
	if col > avail-maxDetail {
		col = avail - maxDetail
	}
	if col < 10 {
		col = 10
	}
	return col
}

// formatPickerLabel fits an item into avail columns. When the item has a
// detail, the label is truncated to end before detailCol and the detail is
// left-aligned at detailCol.
func formatPickerLabel(item pickerItem, avail int, detailCol int) string {
	label := []rune(item.label)
	if item.detail == "" || detailCol <= 0 {
		if len(label) > avail {
			return string(label[:avail-3]) + "..."
		}
		return string(label)
	}

	if len(label) > detailCol-2 {
		label = []rune(string(label[:detailCol-5]) + "...")
	}
	out := []rune(string(label) + strings.Repeat(" ", detailCol-len(label)) + item.detail)
	if len(out) > avail {
		return string(out[:avail-3]) + "..."
	}
	return string(out)
}

// streamingContent returns the display content for the in-progress stream.
func (v *viewport) streamingContent() string {
	if v.streamMarkdown && v.streamRendered != "" {
		return v.streamRendered
	}
	// Fall back to raw text with agent dot prefix
	bufLines := strings.Split(v.streamBuf, "\n")
	if len(bufLines) > 0 {
		bufLines[0] = agentDot + " " + bufLines[0]
		for i := 1; i < len(bufLines); i++ {
			bufLines[i] = "  " + bufLines[i]
		}
	}
	return strings.Join(bufLines, "\n")
}

// totalLines computes the total number of rendered content lines.
func (v *viewport) totalLines() int {
	var lines []string
	for _, e := range v.entries {
		if e.kind == entryCitation && !v.showSources {
			continue
		}
		lines = append(lines, e.rendered)
	}
	if v.streaming && v.streamBuf != "" {
		lines = append(lines, v.streamingContent())
	} else if v.streaming {
		lines = append(lines, agentDot+" ")
	}
	content := strings.Join(lines, "\n")
	return len(strings.Split(content, "\n"))
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

	// Streaming buffer
	if v.streaming && v.streamBuf != "" {
		lines = append(lines, v.streamingContent())
	} else if v.streaming {
		lines = append(lines, agentDot+" ")
	}

	content := strings.Join(lines, "\n")
	contentLines := strings.Split(content, "\n")
	total := len(contentLines)

	maxScroll := total - height
	if maxScroll < 0 {
		maxScroll = 0
	}
	scrollOffset := v.scrollOffset
	if scrollOffset > maxScroll {
		scrollOffset = maxScroll
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
		end := total - scrollOffset
		start := end - height
		if start < 0 {
			start = 0
		}
		contentLines = contentLines[start:end]
	}

	return strings.Join(contentLines, "\n")
}
