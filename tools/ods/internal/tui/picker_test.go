package tui

import (
	"slices"
	"testing"

	"github.com/gdamore/tcell/v2"
)

// pickerGroups is a two-group picker: three items, flat indices 0..2.
var pickerGroups = []PickerGroup{
	{Label: "Group A", Items: []string{"a1", "a2"}},
	{Label: "Group B", Items: []string{"b1"}},
}

func TestBuildEntries_interleavesHeadersAndItems(t *testing.T) {
	entries := buildEntries(pickerGroups)

	want := []entry{
		{label: "Group A", isHeader: true, groupIdx: 0, flatIdx: -1},
		{label: "a1", groupIdx: 0, flatIdx: 0},
		{label: "a2", groupIdx: 0, flatIdx: 1},
		{label: "Group B", isHeader: true, groupIdx: 1, flatIdx: -1},
		{label: "b1", groupIdx: 1, flatIdx: 2},
	}
	if !slices.Equal(entries, want) {
		t.Fatalf("expected %+v, got %+v", want, entries)
	}
	if got := countItems(entries); got != 3 {
		t.Errorf("countItems() = %d, want 3", got)
	}
	if got := countSelected(entries); got != 0 {
		t.Errorf("every item must start deselected, got %d selected", got)
	}
	if got := collectSelected(entries); got != nil {
		t.Errorf("collectSelected() = %v, want nil", got)
	}
}

func TestFirstSelectableIndex_skipsHeaders(t *testing.T) {
	if got := firstSelectableIndex(buildEntries(pickerGroups)); got != 1 {
		t.Errorf("expected the first item at 1, got %d", got)
	}

	// A group with no items leaves nothing to select, so the cursor stays at
	// the top rather than pointing past the end.
	headerOnly := buildEntries([]PickerGroup{{Label: "Group A"}})
	if got := firstSelectableIndex(headerOnly); got != 0 {
		t.Errorf("expected 0 without selectable items, got %d", got)
	}
}

func TestToggleAtCursor_togglesOneItem(t *testing.T) {
	entries := buildEntries(pickerGroups)

	toggleAtCursor(entries, 2)

	if got := collectSelected(entries); !slices.Equal(got, []int{1}) {
		t.Fatalf("expected [1] selected, got %v", got)
	}

	toggleAtCursor(entries, 2)

	if got := countSelected(entries); got != 0 {
		t.Fatalf("a second toggle must deselect, got %d selected", got)
	}
}

func TestToggleAtCursor_onAHeaderTogglesTheWholeGroup(t *testing.T) {
	entries := buildEntries(pickerGroups)

	// A partly selected group selects fully before it deselects.
	toggleAtCursor(entries, 1)
	toggleAtCursor(entries, 0)

	if got := collectSelected(entries); !slices.Equal(got, []int{0, 1}) {
		t.Fatalf("expected the whole group selected, got %v", got)
	}

	toggleAtCursor(entries, 0)

	if got := countSelected(entries); got != 0 {
		t.Fatalf("expected the whole group deselected, got %d selected", got)
	}
}

func TestToggleAtCursor_ignoresAnOutOfRangeCursor(t *testing.T) {
	entries := buildEntries(pickerGroups)

	toggleAtCursor(entries, -1)
	toggleAtCursor(entries, len(entries))

	if got := countSelected(entries); got != 0 {
		t.Fatalf("expected no change, got %d selected", got)
	}
}

func TestSetAll_coversEveryItem(t *testing.T) {
	entries := buildEntries(pickerGroups)

	setAll(entries, true)

	if got := collectSelected(entries); !slices.Equal(got, []int{0, 1, 2}) {
		t.Fatalf("expected every item selected, got %v", got)
	}

	setAll(entries, false)

	if got := collectSelected(entries); got != nil {
		t.Fatalf("expected nothing selected, got %v", got)
	}
}

func TestKeyAction(t *testing.T) {
	tests := []struct {
		name string
		key  tcell.Key
		ch   rune
		want action
	}{
		{name: "escape quits", key: tcell.KeyEscape, want: actionQuit},
		{name: "ctrl-c quits", key: tcell.KeyCtrlC, want: actionQuit},
		{name: "enter confirms", key: tcell.KeyEnter, want: actionConfirm},
		{name: "up arrow", key: tcell.KeyUp, want: actionUp},
		{name: "down arrow", key: tcell.KeyDown, want: actionDown},
		{name: "home", key: tcell.KeyHome, want: actionTop},
		{name: "end", key: tcell.KeyEnd, want: actionBottom},
		{name: "page up", key: tcell.KeyPgUp, want: actionPageUp},
		{name: "page down", key: tcell.KeyPgDn, want: actionPageDown},
		{name: "q quits", key: tcell.KeyRune, ch: 'q', want: actionQuit},
		{name: "space toggles", key: tcell.KeyRune, ch: ' ', want: actionToggle},
		{name: "j moves down", key: tcell.KeyRune, ch: 'j', want: actionDown},
		{name: "k moves up", key: tcell.KeyRune, ch: 'k', want: actionUp},
		{name: "g jumps to the top", key: tcell.KeyRune, ch: 'g', want: actionTop},
		{name: "G jumps to the bottom", key: tcell.KeyRune, ch: 'G', want: actionBottom},
		{name: "a selects all", key: tcell.KeyRune, ch: 'a', want: actionAll},
		{name: "n selects none", key: tcell.KeyRune, ch: 'n', want: actionNone},
		{name: "an unbound rune does nothing", key: tcell.KeyRune, ch: 'z', want: actionNoop},
		{name: "an unbound key does nothing", key: tcell.KeyTab, want: actionNoop},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := keyAction(tcell.NewEventKey(tt.key, tt.ch, tcell.ModNone))
			if got != tt.want {
				t.Fatalf("keyAction() = %d, want %d", got, tt.want)
			}
		})
	}
}
