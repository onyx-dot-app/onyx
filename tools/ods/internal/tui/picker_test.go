package tui

import (
	"testing"
)

// pickerGroups is a two-group picker: three items, flat indices 0..2.
var pickerGroups = []PickerGroup{
	{Label: "Group A", Items: []string{"a1", "a2"}},
	{Label: "Group B", Items: []string{"b1"}},
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
