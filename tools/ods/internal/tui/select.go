package tui

import (
	"fmt"

	"github.com/gdamore/tcell/v2"
)

// Select shows a single-choice list the user moves through with the arrow
// keys. It returns the index of the chosen option, or -1 when the user
// cancels. It returns a non-nil error if the terminal cannot be initialised,
// in which case the caller should fall back to a simpler prompt.
func Select(title string, options []string, defaultIndex int) (int, error) {
	if len(options) == 0 {
		return -1, fmt.Errorf("select needs at least one option")
	}

	screen, err := tcell.NewScreen()
	if err != nil {
		return -1, err
	}
	if err := screen.Init(); err != nil {
		return -1, err
	}
	defer screen.Fini()

	cursor := defaultIndex
	if cursor < 0 || cursor >= len(options) {
		cursor = 0
	}

	for {
		w, h := screen.Size()
		drawSelect(screen, title, options, cursor, w, h)
		screen.Show()

		switch ev := screen.PollEvent().(type) {
		case *tcell.EventResize:
			screen.Sync()
		case *tcell.EventKey:
			switch keyAction(ev) {
			case actionQuit:
				return -1, nil
			case actionConfirm:
				return cursor, nil
			case actionUp:
				if cursor > 0 {
					cursor--
				}
			case actionDown:
				if cursor < len(options)-1 {
					cursor++
				}
			case actionTop:
				cursor = 0
			case actionBottom:
				cursor = len(options) - 1
			}
		}
	}
}

var (
	styleSelectItem = tcell.StyleDefault
	styleSelectCur  = tcell.StyleDefault.Bold(true).Reverse(true)
)

func drawSelect(screen tcell.Screen, title string, options []string, cursor, w, h int) {
	screen.Clear()

	drawLine(screen, 0, 0, w, " "+title, styleTitle)

	// The highlight covers the longest row rather than the whole terminal
	// width, so a wide window does not turn into a full-width bar.
	rowWidth := 0
	for _, option := range options {
		if len(option) > rowWidth {
			rowWidth = len(option)
		}
	}
	rowWidth += len("  > ") + 1
	if rowWidth > w {
		rowWidth = w
	}

	for i, option := range options {
		y := headerLines + i
		if y >= h-footerLines {
			break
		}
		prefix := "    "
		style := styleSelectItem
		if i == cursor {
			prefix = "  > "
			style = styleSelectCur
		}
		drawLine(screen, 0, y, rowWidth, prefix+option, style)
	}

	drawLine(screen, 0, h-1, w, " ↑/↓ move  enter select  q/esc cancel", styleFooter)
}
