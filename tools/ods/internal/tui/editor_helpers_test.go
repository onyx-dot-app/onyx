package tui

import (
	"errors"
	"slices"
	"strings"
	"testing"
)

func TestPadRunes(t *testing.T) {
	tests := []struct {
		in    string
		width int
		want  string
	}{
		{in: "ab", width: 5, want: "ab   "},
		{in: "abc", width: 3, want: "abc"},
		{in: "", width: 3, want: "   "},
		{in: "abcdef", width: 4, want: "abc…"},
		{in: "abc", width: 1, want: "a"},
		{in: "abc", width: 0, want: ""},
	}
	for _, tt := range tests {
		if got := padRunes(tt.in, tt.width); got != tt.want {
			t.Errorf("padRunes(%q, %d) = %q, want %q", tt.in, tt.width, got, tt.want)
		}
	}
}

func TestRenderCells_padsAndSeparatesTheColumns(t *testing.T) {
	got := renderCells([]int{3, 4}, []string{"a", "bb"})

	if want := "a  " + "  " + "bb  "; got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestEntryWord_agreesWithTheCount(t *testing.T) {
	if got := entryWord(1); got != "entry" {
		t.Errorf("entryWord(1) = %q, want %q", got, "entry")
	}
	for _, n := range []int{0, 2, 17} {
		if got := entryWord(n); got != "entries" {
			t.Errorf("entryWord(%d) = %q, want %q", n, got, "entries")
		}
	}
}

func TestCloneRows_copiesEveryMap(t *testing.T) {
	rows := []map[string]string{{"id": "A"}, {"id": "B"}}

	clone := cloneRows(rows)
	clone[0]["id"] = "CHANGED"

	if rows[0]["id"] != "A" {
		t.Fatalf("editing the clone changed the original: %v", rows[0])
	}
	if len(clone) != 2 || clone[1]["id"] != "B" {
		t.Fatalf("unexpected clone: %v", clone)
	}
	if got := cloneRows(nil); len(got) != 0 {
		t.Fatalf("cloneRows(nil) = %v, want an empty slice", got)
	}
}

func TestVisibleRows_staysAtLeastOne(t *testing.T) {
	chrome := tableHeaderLines + tableFooterLines

	tests := []struct {
		height int
		want   int
	}{
		{height: chrome + 10, want: 10},
		{height: chrome + 2, want: 2},
		{height: chrome + 1, want: 1},
		{height: chrome, want: 1},
		{height: 0, want: 1},
	}
	for _, tt := range tests {
		if got := visibleRows(tt.height); got != tt.want {
			t.Errorf("visibleRows(%d) = %d, want %d", tt.height, got, tt.want)
		}
	}
}

func TestValidateRow(t *testing.T) {
	rejectShort := func(v string) error {
		if len(v) < 3 {
			return errors.New("too short")
		}
		return nil
	}
	cols := []Column{
		{Key: "id", Title: "ID", Required: true},
		{Key: "note", Title: "Note", Validate: rejectShort},
	}

	tests := []struct {
		name string
		row  map[string]string
		// wantErr is a substring of the expected message; empty means the row
		// must pass.
		wantErr string
	}{
		{name: "complete row", row: map[string]string{"id": "GHSA-1", "note": "hello"}},
		{name: "empty optional value skips its check", row: map[string]string{"id": "GHSA-1", "note": ""}},
		{name: "missing required value", row: map[string]string{"note": "hello"}, wantErr: "ID is required"},
		{name: "blank required value", row: map[string]string{"id": "   "}, wantErr: "ID is required"},
		{name: "rejected optional value", row: map[string]string{"id": "GHSA-1", "note": "hi"}, wantErr: "Note: too short"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateRow(cols, tt.row)
			if tt.wantErr == "" {
				if err != nil {
					t.Fatalf("expected the row to pass, got %v", err)
				}
				return
			}
			if err == nil {
				t.Fatalf("expected an error containing %q", tt.wantErr)
			}
			if !strings.Contains(err.Error(), tt.wantErr) {
				t.Fatalf("expected an error containing %q, got %q", tt.wantErr, err.Error())
			}
		})
	}
}

func TestMoveCursor_clampsToTheRows(t *testing.T) {
	ed := &rowEditor{
		cols: testCols,
		rows: []map[string]string{{"id": "A"}, {"id": "B"}, {"id": "C"}},
	}

	ed.moveCursor(1)
	if ed.cursor != 1 {
		t.Fatalf("expected the cursor at 1, got %d", ed.cursor)
	}
	ed.moveCursor(10)
	if ed.cursor != ed.lastIndex() {
		t.Fatalf("expected the cursor at the last row %d, got %d", ed.lastIndex(), ed.cursor)
	}
	ed.moveCursor(-10)
	if ed.cursor != 0 {
		t.Fatalf("expected the cursor at 0, got %d", ed.cursor)
	}
}

func TestMoveCursor_holdsAtZeroWithoutRows(t *testing.T) {
	ed := &rowEditor{cols: testCols}

	ed.moveCursor(5)

	if ed.lastIndex() != 0 || ed.cursor != 0 {
		t.Fatalf("expected an empty editor to stay at 0, got cursor %d", ed.cursor)
	}
}

func TestColumnWidths_fitTheTitlesAndValues(t *testing.T) {
	long := strings.Repeat("x", 60)
	ed := &rowEditor{
		cols: testCols,
		rows: []map[string]string{
			{"id": "GHSA-1", "note": "hi"},
			{"id": "G", "note": long},
		},
	}

	widths := ed.columnWidths()

	// "ID" is shorter than "GHSA-1", and the note column caps at 48 columns.
	if want := []int{len("GHSA-1"), 48}; !slices.Equal(widths, want) {
		t.Fatalf("expected %v, got %v", want, widths)
	}
}

func TestColumnWidths_fallBackToTheTitles(t *testing.T) {
	ed := &rowEditor{cols: testCols}

	widths := ed.columnWidths()

	if want := []int{len("ID"), len("Note")}; !slices.Equal(widths, want) {
		t.Fatalf("expected %v, got %v", want, widths)
	}
}
