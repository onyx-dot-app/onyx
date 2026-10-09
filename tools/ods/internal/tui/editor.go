package tui

import (
	"fmt"
	"strings"

	"github.com/gdamore/tcell/v2"
)

// Column describes one editable field, rendered both as a table column and as a
// form field.
type Column struct {
	Key      string
	Title    string
	Required bool
	// Default prefills the field when adding a new row (ignored when editing).
	Default string
	// Validate is an optional per-field check applied to non-empty values when a
	// form is submitted. Return a non-nil error to reject the value.
	Validate func(string) error
}

// EditRows shows a full-screen table of rows with add/edit/delete and
// save/cancel. Each row maps a column key to its value. It returns the edited
// rows and whether the user chose to save (false = cancelled). A non-nil error
// means the terminal could not be initialized, in which case the caller should
// fall back to a non-TUI path.
func EditRows(title string, cols []Column, rows []map[string]string) ([]map[string]string, bool, error) {
	screen, err := tcell.NewScreen()
	if err != nil {
		return nil, false, err
	}
	if err := screen.Init(); err != nil {
		return nil, false, err
	}
	defer screen.Fini()

	rows, saved := runEditor(screen, title, cols, rows)
	return rows, saved, nil
}

// runEditor drives the editor on an already-initialized screen. Split out from
// EditRows so it can be exercised with a tcell SimulationScreen in tests.
func runEditor(screen tcell.Screen, title string, cols []Column, rows []map[string]string) ([]map[string]string, bool) {
	ed := &rowEditor{
		screen: screen,
		title:  title,
		cols:   cols,
		rows:   cloneRows(rows),
	}
	saved := ed.run()
	return ed.rows, saved
}

type rowEditor struct {
	screen tcell.Screen
	title  string
	cols   []Column
	rows   []map[string]string
	cursor int
}

const (
	tableHeaderLines = 4 // title, blank, column header, blank
	tableFooterLines = 2 // blank + keybinds
)

var (
	styleTableTitle   = tcell.StyleDefault.Bold(true)
	styleTableHeader  = tcell.StyleDefault.Bold(true).Foreground(tcell.ColorTeal)
	styleRow          = tcell.StyleDefault
	styleRowCursor    = tcell.StyleDefault.Reverse(true)
	styleFormLabel    = tcell.StyleDefault
	styleFormLabelAct = tcell.StyleDefault.Bold(true).Foreground(tcell.ColorTeal)
	styleFormValue    = tcell.StyleDefault
	styleError        = tcell.StyleDefault.Foreground(tcell.ColorRed).Bold(true)
	styleHint         = tcell.StyleDefault.Dim(true)
)

// --- table loop --------------------------------------------------------------

func (ed *rowEditor) run() bool {
	offset := 0
	for {
		_, h := ed.screen.Size()
		ed.drawTable(offset)
		ed.screen.Show()

		switch ev := ed.screen.PollEvent().(type) {
		case *tcell.EventResize:
			ed.screen.Sync()
		case *tcell.EventKey:
			switch ev.Key() {
			case tcell.KeyEscape, tcell.KeyCtrlC:
				return false
			case tcell.KeyUp:
				ed.moveCursor(-1)
			case tcell.KeyDown:
				ed.moveCursor(1)
			case tcell.KeyHome:
				ed.cursor = 0
			case tcell.KeyEnd:
				ed.cursor = ed.lastIndex()
			case tcell.KeyPgUp:
				ed.moveCursor(-visibleRows(h))
			case tcell.KeyPgDn:
				ed.moveCursor(visibleRows(h))
			case tcell.KeyEnter:
				ed.doEdit()
			case tcell.KeyRune:
				switch ev.Rune() {
				case 'q':
					return false
				case 'j':
					ed.moveCursor(1)
				case 'k':
					ed.moveCursor(-1)
				case 'g':
					ed.cursor = 0
				case 'G':
					ed.cursor = ed.lastIndex()
				case 'a':
					ed.doAdd()
				case 'e':
					ed.doEdit()
				case 'd':
					ed.doDelete()
				case 's':
					return true
				}
			}
		}

		listHeight := visibleRows(h)
		if ed.cursor < offset {
			offset = ed.cursor
		}
		if ed.cursor >= offset+listHeight {
			offset = ed.cursor - listHeight + 1
		}
		if offset < 0 {
			offset = 0
		}
	}
}

func (ed *rowEditor) lastIndex() int {
	if len(ed.rows) == 0 {
		return 0
	}
	return len(ed.rows) - 1
}

func (ed *rowEditor) moveCursor(delta int) {
	ed.cursor += delta
	if ed.cursor < 0 {
		ed.cursor = 0
	}
	if ed.cursor > ed.lastIndex() {
		ed.cursor = ed.lastIndex()
	}
}

// visibleRows is the number of table rows that fit on a screen of height h,
// always at least 1 so paging stays directionally correct on tiny terminals.
func visibleRows(h int) int {
	if n := h - tableHeaderLines - tableFooterLines; n > 1 {
		return n
	}
	return 1
}

func (ed *rowEditor) doAdd() {
	empty := make(map[string]string, len(ed.cols))
	for _, c := range ed.cols {
		empty[c.Key] = c.Default
	}
	if row, ok := ed.editForm("Add entry", empty); ok {
		ed.rows = append(ed.rows, row)
		ed.cursor = len(ed.rows) - 1
	}
}

func (ed *rowEditor) doEdit() {
	if len(ed.rows) == 0 {
		return
	}
	if row, ok := ed.editForm("Edit entry", ed.rows[ed.cursor]); ok {
		ed.rows[ed.cursor] = row
	}
}

func (ed *rowEditor) doDelete() {
	if len(ed.rows) == 0 {
		return
	}
	if !ed.confirm(fmt.Sprintf("Delete entry %q?  (y/N)", ed.rowLabel(ed.cursor))) {
		return
	}
	ed.rows = append(ed.rows[:ed.cursor], ed.rows[ed.cursor+1:]...)
	if ed.cursor > ed.lastIndex() {
		ed.cursor = ed.lastIndex()
	}
}

func (ed *rowEditor) rowLabel(i int) string {
	if len(ed.cols) == 0 {
		return ""
	}
	return ed.rows[i][ed.cols[0].Key]
}

// --- form loop ---------------------------------------------------------------

// editForm shows a modal form for a single row and returns the edited row plus
// whether it was confirmed. Values are trimmed and validated on submit.
func (ed *rowEditor) editForm(title string, initial map[string]string) (map[string]string, bool) {
	values := make([][]rune, len(ed.cols))
	for i, c := range ed.cols {
		values[i] = []rune(initial[c.Key])
	}
	active := 0
	caret := len(values[active])
	errMsg := ""

	labelWidth := 0
	for _, c := range ed.cols {
		if l := len([]rune(c.Title)); l > labelWidth {
			labelWidth = l
		}
	}

	for {
		ed.drawForm(title, values, active, caret, labelWidth, errMsg)
		ed.screen.Show()

		switch ev := ed.screen.PollEvent().(type) {
		case *tcell.EventResize:
			ed.screen.Sync()
		case *tcell.EventKey:
			switch ev.Key() {
			case tcell.KeyEscape, tcell.KeyCtrlC:
				return nil, false
			case tcell.KeyEnter:
				row := make(map[string]string, len(ed.cols))
				for i, c := range ed.cols {
					row[c.Key] = strings.TrimSpace(string(values[i]))
				}
				if err := validateRow(ed.cols, row); err != nil {
					errMsg = err.Error()
					continue
				}
				return row, true
			case tcell.KeyTab, tcell.KeyDown:
				active = (active + 1) % len(ed.cols)
				caret = len(values[active])
				errMsg = ""
			case tcell.KeyBacktab, tcell.KeyUp:
				active = (active - 1 + len(ed.cols)) % len(ed.cols)
				caret = len(values[active])
				errMsg = ""
			case tcell.KeyLeft:
				if caret > 0 {
					caret--
				}
			case tcell.KeyRight:
				if caret < len(values[active]) {
					caret++
				}
			case tcell.KeyHome:
				caret = 0
			case tcell.KeyEnd:
				caret = len(values[active])
			case tcell.KeyBackspace, tcell.KeyBackspace2:
				if caret > 0 {
					values[active] = append(values[active][:caret-1], values[active][caret:]...)
					caret--
				}
			case tcell.KeyDelete:
				if caret < len(values[active]) {
					values[active] = append(values[active][:caret], values[active][caret+1:]...)
				}
			case tcell.KeyRune:
				v := values[active]
				nv := make([]rune, 0, len(v)+1)
				nv = append(nv, v[:caret]...)
				nv = append(nv, ev.Rune())
				nv = append(nv, v[caret:]...)
				values[active] = nv
				caret++
			}
		}
	}
}

func validateRow(cols []Column, row map[string]string) error {
	for _, c := range cols {
		v := row[c.Key]
		if c.Required && strings.TrimSpace(v) == "" {
			return fmt.Errorf("%s is required", c.Title)
		}
		if c.Validate != nil && v != "" {
			if err := c.Validate(v); err != nil {
				return fmt.Errorf("%s: %v", c.Title, err)
			}
		}
	}
	return nil
}

// confirm draws a single-line yes/no prompt over the current screen (default No)
// and returns the answer.
func (ed *rowEditor) confirm(msg string) bool {
	for {
		w, h := ed.screen.Size()
		drawLine(ed.screen, 0, h-1, w, " "+msg, styleError)
		ed.screen.Show()
		switch ev := ed.screen.PollEvent().(type) {
		case *tcell.EventResize:
			ed.screen.Sync()
		case *tcell.EventKey:
			switch ev.Key() {
			case tcell.KeyEscape, tcell.KeyCtrlC, tcell.KeyEnter:
				return false
			case tcell.KeyRune:
				switch ev.Rune() {
				case 'y', 'Y':
					return true
				case 'n', 'N':
					return false
				}
			}
		}
	}
}

// --- drawing -----------------------------------------------------------------

func (ed *rowEditor) drawTable(offset int) {
	s := ed.screen
	s.Clear()
	s.HideCursor()
	w, h := s.Size()

	widths := ed.columnWidths()

	title := fmt.Sprintf(" %s  (%d %s)", ed.title, len(ed.rows), entryWord(len(ed.rows)))
	drawLine(s, 0, 0, w, title, styleTableTitle)

	headerCells := make([]string, len(ed.cols))
	for i, c := range ed.cols {
		headerCells[i] = c.Title
	}
	drawLine(s, 0, 2, w, "  "+renderCells(widths, headerCells), styleTableHeader)

	listTop := tableHeaderLines
	listHeight := visibleRows(h)

	if len(ed.rows) == 0 {
		drawLine(s, 0, listTop, w, "  (no entries — press 'a' to add)", styleHint)
	}

	for i := 0; i < listHeight; i++ {
		ri := offset + i
		if ri >= len(ed.rows) {
			break
		}
		y := listTop + i
		cells := make([]string, len(ed.cols))
		for j, c := range ed.cols {
			cells[j] = ed.rows[ri][c.Key]
		}
		prefix := "  "
		style := styleRow
		if ri == ed.cursor {
			prefix = "> "
			style = styleRowCursor
		}
		drawLine(s, 0, y, w, prefix+renderCells(widths, cells), style)
	}

	if len(ed.rows) > listHeight {
		drawScrollbar(s, w-1, listTop, listHeight, offset, len(ed.rows))
	}

	footer := " ↑/↓ move  a add  e/enter edit  d delete  s save  q/esc cancel"
	drawLine(s, 0, h-1, w, footer, styleFooter)
}

func (ed *rowEditor) drawForm(title string, values [][]rune, active, caret, labelWidth int, errMsg string) {
	s := ed.screen
	s.Clear()
	s.HideCursor()
	w, h := s.Size()

	drawLine(s, 0, 0, w, " "+title, styleTableTitle)

	startY := 2
	for i, c := range ed.cols {
		y := startY + i
		labelStyle := styleFormLabel
		if i == active {
			labelStyle = styleFormLabelAct
		}
		req := " "
		if c.Required {
			req = "*"
		}
		x := drawStr(s, 0, y, w, "  ", labelStyle)
		x = drawStr(s, x, y, w, padRunes(c.Title, labelWidth), labelStyle)
		x = drawStr(s, x, y, w, " "+req+" : ", labelStyle)
		valX := x
		drawLine(s, valX, y, w, string(values[i]), styleFormValue)
		if i == active {
			if cx := valX + caret; cx < w {
				s.ShowCursor(cx, y)
			}
		}
	}

	if errMsg != "" {
		drawLine(s, 0, startY+len(ed.cols)+1, w, "  "+errMsg, styleError)
	}

	footer := " Tab/↑↓ field  ←/→ move  Enter save  Esc cancel   (* required)"
	drawLine(s, 0, h-1, w, footer, styleFooter)
}

func (ed *rowEditor) columnWidths() []int {
	const maxCol = 48
	widths := make([]int, len(ed.cols))
	for i, c := range ed.cols {
		widths[i] = len([]rune(c.Title))
	}
	for _, row := range ed.rows {
		for i, c := range ed.cols {
			if l := len([]rune(row[c.Key])); l > widths[i] {
				widths[i] = l
			}
		}
	}
	for i := range widths {
		if widths[i] > maxCol {
			widths[i] = maxCol
		}
	}
	return widths
}

// --- small helpers -----------------------------------------------------------

func renderCells(widths []int, cells []string) string {
	var b strings.Builder
	for i, cell := range cells {
		if i > 0 {
			b.WriteString("  ")
		}
		b.WriteString(padRunes(cell, widths[i]))
	}
	return b.String()
}

// padRunes pads s with spaces to width, or truncates with an ellipsis when
// longer.
func padRunes(s string, width int) string {
	r := []rune(s)
	if len(r) > width {
		if width <= 1 {
			return string(r[:width])
		}
		return string(r[:width-1]) + "…"
	}
	return s + strings.Repeat(" ", width-len(r))
}

func entryWord(n int) string {
	if n == 1 {
		return "entry"
	}
	return "entries"
}

func cloneRows(rows []map[string]string) []map[string]string {
	out := make([]map[string]string, len(rows))
	for i, r := range rows {
		m := make(map[string]string, len(r))
		for k, v := range r {
			m[k] = v
		}
		out[i] = m
	}
	return out
}
