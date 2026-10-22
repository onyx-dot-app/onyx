package tui

import (
	"errors"
	"strings"
	"testing"

	"github.com/gdamore/tcell/v2"
)

var selectOptions = []string{"alpha", "beta", "gamma"}

func runSelectScript(t *testing.T, w, h int, defaultIndex int, sc script) (int, []frame, error) {
	t.Helper()
	var index int
	var err error
	frames := runScripted(t, w, h, sc, func(screen tcell.Screen) {
		index, err = runSelect(screen, "Pick one", selectOptions, defaultIndex)
	})
	return index, frames, err
}

func TestRunSelect_returnsTheChosenIndex(t *testing.T) {
	tests := []struct {
		name         string
		defaultIndex int
		script       script
		want         int
	}{
		{name: "enter keeps the default", defaultIndex: 1, script: script{}.key(tcell.KeyEnter), want: 1},
		{name: "down stops at the last option", defaultIndex: 1, script: script{}.key(tcell.KeyDown).key(tcell.KeyDown).key(tcell.KeyUp).key(tcell.KeyEnter), want: 1},
		{name: "up stops at the first option", defaultIndex: 1, script: script{}.key(tcell.KeyUp).key(tcell.KeyUp).key(tcell.KeyDown).key(tcell.KeyEnter), want: 1},
		{name: "j and k move", defaultIndex: 0, script: script{}.text("jjk").key(tcell.KeyEnter), want: 1},
		{name: "end jumps to the last option", defaultIndex: 0, script: script{}.key(tcell.KeyEnd).key(tcell.KeyEnter), want: 2},
		{name: "g jumps to the first option", defaultIndex: 2, script: script{}.text("g").key(tcell.KeyEnter), want: 0},
		{name: "keys without a select action are ignored", defaultIndex: 1, script: script{}.text("xa ").key(tcell.KeyEnter), want: 1},
		{name: "a default past the end starts at the top", defaultIndex: 7, script: script{}.key(tcell.KeyEnter), want: 0},
		{name: "a negative default starts at the top", defaultIndex: -1, script: script{}.key(tcell.KeyEnter), want: 0},
		{name: "escape cancels", defaultIndex: 1, script: script{}.key(tcell.KeyDown).key(tcell.KeyEscape), want: -1},
		{name: "q cancels", defaultIndex: 1, script: script{}.text("q"), want: -1},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, _, err := runSelectScript(t, 40, 10, tt.defaultIndex, tt.script)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.want {
				t.Fatalf("expected %d, got %d", tt.want, got)
			}
		})
	}
}

func TestRunSelect_highlightsTheCursorRowOnly(t *testing.T) {
	_, frames, _ := runSelectScript(t, 40, 10, 0, script{}.key(tcell.KeyDown).key(tcell.KeyEnter))
	f := frames[1]

	if got := f.row(0); got != " Pick one" {
		t.Errorf("expected the title on row 0, got %q", got)
	}
	if got := f.row(2); got != "    alpha" {
		t.Errorf("expected alpha unmarked, got %q", got)
	}
	if got := f.row(3); got != "  > beta" {
		t.Errorf("expected beta marked, got %q", got)
	}
	if !hasAttr(f.style(0, 3), tcell.AttrReverse) {
		t.Error("expected the cursor row to be reversed")
	}
	if hasAttr(f.style(0, 2), tcell.AttrReverse) {
		t.Error("expected other rows not to be reversed")
	}
	// The bar spans the longest option plus the "  > " prefix and one space.
	barWidth := len("  > ") + len("alpha") + 1
	if !hasAttr(f.style(barWidth-1, 3), tcell.AttrReverse) || hasAttr(f.style(barWidth, 3), tcell.AttrReverse) {
		t.Errorf("expected the highlight to end at column %d", barWidth)
	}
	if got := f.row(9); !strings.HasPrefix(got, " ↑/↓ move") {
		t.Errorf("expected the key help on the last row, got %q", got)
	}
}

func TestRunSelect_clipsToASmallScreen(t *testing.T) {
	// Height 5 leaves one list row between the title and the footer; width 6
	// cuts the rows short.
	_, frames, _ := runSelectScript(t, 6, 5, 0, script{}.key(tcell.KeyEnter))
	f := frames[0]

	if got := f.row(2); got != "  > al" {
		t.Errorf("expected the first option cut at the screen edge, got %q", got)
	}
	if got := f.row(3); got != "" {
		t.Errorf("expected no option on the row above the footer, got %q", got)
	}
}

func TestRunSelect_redrawsAtTheNewSizeAfterAResize(t *testing.T) {
	got, frames, err := runSelectScript(t, 40, 10, 0, script{}.resize(40, 6).key(tcell.KeyDown).key(tcell.KeyEnter))
	if err != nil || got != 1 {
		t.Fatalf("expected (1, nil), got (%d, %v)", got, err)
	}

	f := frames[1]
	if len(f.lines) != 6 {
		t.Fatalf("expected a 6-row screen, got %d rows", len(f.lines))
	}
	if !strings.HasPrefix(f.row(5), " ↑/↓ move") {
		t.Errorf("expected the key help on the new last row, got %q", f.row(5))
	}
	if f.row(4) != "" {
		t.Errorf("expected gamma dropped above the footer, got %q", f.row(4))
	}
}

func TestRunSelect_failsWhenTheTerminalStops(t *testing.T) {
	got, _, err := runSelectScript(t, 40, 10, 0, script{}.event(nil))
	if got != -1 || err == nil || !strings.Contains(err.Error(), "stopped delivering events") {
		t.Fatalf("expected (-1, stopped delivering events), got (%d, %v)", got, err)
	}
}

func TestRunSelect_failsOnATerminalError(t *testing.T) {
	cause := errors.New("tty went away")
	got, _, err := runSelectScript(t, 40, 10, 0, script{}.event(tcell.NewEventError(cause)))

	var evErr *tcell.EventError
	if got != -1 || !errors.As(err, &evErr) || !strings.Contains(err.Error(), "tty went away") {
		t.Fatalf("expected (-1, terminal error), got (%d, %v)", got, err)
	}
}

func TestSelect_rejectsAnEmptyOptionList(t *testing.T) {
	// The check runs before any terminal is opened.
	got, err := Select("Pick one", nil, 0)
	if got != -1 || err == nil {
		t.Fatalf("expected (-1, error), got (%d, %v)", got, err)
	}
}
