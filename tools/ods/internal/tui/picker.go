package tui

import (
	"fmt"

	"github.com/gdamore/tcell/v2"
)

// PickerGroup represents a labelled group of selectable items.
type PickerGroup struct {
	Label string
	Items []string
}

// entry is a single row in the picker (either a group header or an item).
type entry struct {
	label    string
	isHeader bool
	selected bool
	groupIdx int
	flatIdx  int // index across all items (ignoring headers), -1 for headers
}

// Pick shows a full-screen grouped multi-select picker.
// All items start deselected. Returns the flat indices of selected items
// (0-based, spanning all groups in order). Returns nil if cancelled.
// Returns a non-nil error if the terminal cannot be initialised, in which
// case the caller should fall back to a simpler prompt.
func Pick(groups []PickerGroup) ([]int, error) {
	screen, err := tcell.NewScreen()
	if err != nil {
		return nil, err
	}
	if err := screen.Init(); err != nil {
		return nil, err
	}
	defer screen.Fini()

	entries := buildEntries(groups)
	totalItems := countItems(entries)
	cursor := firstSelectableIndex(entries)
	offset := 0

	for {
		w, h := screen.Size()
		selectedCount := countSelected(entries)

		drawPicker(screen, entries, groups, cursor, offset, w, h, selectedCount, totalItems)
		screen.Show()

		ev := screen.PollEvent()
		switch ev := ev.(type) {
		case *tcell.EventResize:
			screen.Sync()
		case *tcell.EventKey:
			switch action := keyAction(ev); action {
			case actionQuit:
				return nil, nil
			case actionConfirm:
				return collectSelected(entries), nil
			case actionUp:
				if cursor > 0 {
					cursor--
				}
			case actionDown:
				if cursor < len(entries)-1 {
					cursor++
				}
			case actionTop:
				cursor = 0
			case actionBottom:
				if len(entries) == 0 {
					cursor = 0
				} else {
					cursor = len(entries) - 1
				}
			case actionPageUp:
				listHeight := h - headerLines - footerLines
				cursor -= listHeight
				if cursor < 0 {
					cursor = 0
				}
			case actionPageDown:
				listHeight := h - headerLines - footerLines
				cursor += listHeight
				if cursor >= len(entries) {
					cursor = len(entries) - 1
				}
			case actionToggle:
				toggleAtCursor(entries, cursor)
			case actionAll:
				setAll(entries, true)
			case actionNone:
				setAll(entries, false)
			}

			// Keep the cursor visible
			listHeight := h - headerLines - footerLines
			if listHeight < 1 {
				listHeight = 1
			}
			if cursor < offset {
				offset = cursor
			}
			if cursor >= offset+listHeight {
				offset = cursor - listHeight + 1
			}
		}
	}
}

// --- actions ----------------------------------------------------------------

type action int

const (
	actionNoop action = iota
	actionQuit
	actionConfirm
	actionUp
	actionDown
	actionTop
	actionBottom
	actionPageUp
	actionPageDown
	actionToggle
	actionAll
	actionNone
)

func keyAction(ev *tcell.EventKey) action {
	switch ev.Key() {
	case tcell.KeyEscape, tcell.KeyCtrlC:
		return actionQuit
	case tcell.KeyEnter:
		return actionConfirm
	case tcell.KeyUp:
		return actionUp
	case tcell.KeyDown:
		return actionDown
	case tcell.KeyHome:
		return actionTop
	case tcell.KeyEnd:
		return actionBottom
	case tcell.KeyPgUp:
		return actionPageUp
	case tcell.KeyPgDn:
		return actionPageDown
	case tcell.KeyRune:
		switch ev.Rune() {
		case 'q':
			return actionQuit
		case ' ':
			return actionToggle
		case 'j':
			return actionDown
		case 'k':
			return actionUp
		case 'g':
			return actionTop
		case 'G':
			return actionBottom
		case 'a':
			return actionAll
		case 'n':
			return actionNone
		}
	}
	return actionNoop
}

// --- data helpers ------------------------------------------------------------

func buildEntries(groups []PickerGroup) []entry {
	var entries []entry
	flat := 0
	for gi, g := range groups {
		entries = append(entries, entry{
			label:    g.Label,
			isHeader: true,
			groupIdx: gi,
			flatIdx:  -1,
		})
		for _, item := range g.Items {
			entries = append(entries, entry{
				label:    item,
				isHeader: false,
				selected: false,
				groupIdx: gi,
				flatIdx:  flat,
			})
			flat++
		}
	}
	return entries
}

func firstSelectableIndex(entries []entry) int {
	for i, e := range entries {
		if !e.isHeader {
			return i
		}
	}
	return 0
}

func countItems(entries []entry) int {
	n := 0
	for _, e := range entries {
		if !e.isHeader {
			n++
		}
	}
	return n
}

func countSelected(entries []entry) int {
	n := 0
	for _, e := range entries {
		if !e.isHeader && e.selected {
			n++
		}
	}
	return n
}

func collectSelected(entries []entry) []int {
	var result []int
	for _, e := range entries {
		if !e.isHeader && e.selected {
			result = append(result, e.flatIdx)
		}
	}
	return result
}

func toggleAtCursor(entries []entry, cursor int) {
	e := entries[cursor]
	if e.isHeader {
		// Toggle entire group: if all selected -> deselect all, else select all
		allSelected := true
		for _, e2 := range entries {
			if !e2.isHeader && e2.groupIdx == e.groupIdx && !e2.selected {
				allSelected = false
				break
			}
		}
		for i := range entries {
			if !entries[i].isHeader && entries[i].groupIdx == e.groupIdx {
				entries[i].selected = !allSelected
			}
		}
	} else {
		entries[cursor].selected = !entries[cursor].selected
	}
}

func setAll(entries []entry, selected bool) {
	for i := range entries {
		if !entries[i].isHeader {
			entries[i].selected = selected
		}
	}
}

// --- drawing ----------------------------------------------------------------

const (
	headerLines = 2 // title + blank line
	footerLines = 2 // blank line + keybinds
)

var (
	styleDefault    = tcell.StyleDefault
	styleTitle      = tcell.StyleDefault.Bold(true)
	styleGroup      = tcell.StyleDefault.Bold(true).Foreground(tcell.ColorTeal)
	styleGroupCur   = tcell.StyleDefault.Bold(true).Foreground(tcell.ColorTeal).Reverse(true)
	styleCheck      = tcell.StyleDefault.Foreground(tcell.ColorGreen).Bold(true)
	styleUncheck    = tcell.StyleDefault.Dim(true)
	styleItem       = tcell.StyleDefault
	styleItemCur    = tcell.StyleDefault.Bold(true).Underline(true)
	styleCheckCur   = tcell.StyleDefault.Foreground(tcell.ColorGreen).Bold(true).Underline(true)
	styleUncheckCur = tcell.StyleDefault.Dim(true).Underline(true)
	styleFooter     = tcell.StyleDefault.Dim(true)
)

func drawPicker(
	screen tcell.Screen,
	entries []entry,
	groups []PickerGroup,
	cursor, offset, w, h, selectedCount, totalItems int,
) {
	screen.Clear()

	// Title
	title := fmt.Sprintf(" Select traces to open (%d/%d selected)", selectedCount, totalItems)
	drawLine(screen, 0, 0, w, title, styleTitle)

	// List area
	listHeight := h - headerLines - footerLines
	if listHeight < 1 {
		listHeight = 1
	}

	for i := 0; i < listHeight; i++ {
		ei := offset + i
		if ei >= len(entries) {
			break
		}
		y := headerLines + i
		renderEntry(screen, entries, groups, ei, cursor, w, y)
	}

	// Scrollbar hint
	if len(entries) > listHeight {
		drawScrollbar(screen, w-1, headerLines, listHeight, offset, len(entries))
	}

	// Footer
	footerY := h - 1
	footer := " ↑/↓ move  space toggle  a all  n none  enter open  q/esc quit"
	drawLine(screen, 0, footerY, w, footer, styleFooter)
}

func renderEntry(screen tcell.Screen, entries []entry, groups []PickerGroup, ei, cursor, w, y int) {
	e := entries[ei]
	isCursor := ei == cursor

	if e.isHeader {
		groupSelected := 0
		groupTotal := 0
		for _, e2 := range entries {
			if !e2.isHeader && e2.groupIdx == e.groupIdx {
				groupTotal++
				if e2.selected {
					groupSelected++
				}
			}
		}

		label := fmt.Sprintf("  %s (%d/%d)", e.label, groupSelected, groupTotal)
		style := styleGroup
		if isCursor {
			style = styleGroupCur
		}
		drawLine(screen, 0, y, w, label, style)
		return
	}

	// Item row: "    [x] label" or "  > [x] label"
	prefix := "    "
	if isCursor {
		prefix = "  > "
	}

	check := "[ ]"
	cStyle := styleUncheck
	iStyle := styleItem
	if isCursor {
		cStyle = styleUncheckCur
		iStyle = styleItemCur
	}
	if e.selected {
		check = "[x]"
		cStyle = styleCheck
		if isCursor {
			cStyle = styleCheckCur
		}
	}

	x := drawStr(screen, 0, y, w, prefix, iStyle)
	x = drawStr(screen, x, y, w, check, cStyle)
	drawStr(screen, x, y, w, " "+e.label, iStyle)
}

func drawScrollbar(screen tcell.Screen, x, top, height, offset, total int) {
	if total <= height || height < 1 {
		return
	}

	thumbSize := max(1, height*height/total)
	thumbPos := top + offset*height/total

	for y := top; y < top+height; y++ {
		ch := '│'
		style := styleDefault.Dim(true)
		if y >= thumbPos && y < thumbPos+thumbSize {
			ch = '┃'
			style = styleDefault
		}
		screen.SetContent(x, y, ch, nil, style)
	}
}

// drawLine fills an entire row starting at x=startX, padding to width w.
func drawLine(screen tcell.Screen, startX, y, w int, s string, style tcell.Style) {
	x := drawStr(screen, startX, y, w, s, style)
	// Clear the rest of the line
	for ; x < w; x++ {
		screen.SetContent(x, y, ' ', nil, style)
	}
}

// drawStr writes a string at (x, y) up to maxX and returns the next x position.
func drawStr(screen tcell.Screen, x, y, maxX int, s string, style tcell.Style) int {
	for _, ch := range s {
		if x >= maxX {
			break
		}
		screen.SetContent(x, y, ch, nil, style)
		x++
	}
	return x
}
