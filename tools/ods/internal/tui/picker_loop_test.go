package tui

import (
	"slices"
	"strings"
	"testing"

	"github.com/gdamore/tcell/v2"
)

// runPickerScript runs the picker on pickerGroups, whose rows are:
// 0 "Group A", 1 "a1", 2 "a2", 3 "Group B", 4 "b1". The cursor starts on a1.
func runPickerScript(t *testing.T, w, h int, sc script) ([]int, []frame) {
	t.Helper()
	return runPickerGroupsScript(t, w, h, pickerGroups, sc)
}

func runPickerGroupsScript(t *testing.T, w, h int, groups []PickerGroup, sc script) ([]int, []frame) {
	t.Helper()
	var selected []int
	frames := runScripted(t, w, h, sc, func(screen tcell.Screen) {
		selected = runPicker(screen, groups)
	})
	return selected, frames
}

func TestRunPicker_returnsTheSelectedItems(t *testing.T) {
	tests := []struct {
		name   string
		script script
		want   []int
	}{
		{name: "space toggles the item under the cursor", script: script{}.text(" ").key(tcell.KeyEnter), want: []int{0}},
		{name: "space on a header toggles its group", script: script{}.text("jj ").key(tcell.KeyEnter), want: []int{2}},
		{name: "enter waits until something is selected", script: script{}.key(tcell.KeyEnter).text("j ").key(tcell.KeyEnter), want: []int{1}},
		{name: "a selects every item", script: script{}.text("a").key(tcell.KeyEnter), want: []int{0, 1, 2}},
		{name: "n clears the selection", script: script{}.text("an ").key(tcell.KeyEnter), want: []int{0}},
		{name: "down stops at the last row", script: script{}.key(tcell.KeyDown).key(tcell.KeyDown).key(tcell.KeyDown).key(tcell.KeyDown).text(" ").key(tcell.KeyEnter), want: []int{2}},
		{name: "up stops at the first row", script: script{}.key(tcell.KeyUp).key(tcell.KeyUp).text("j ").key(tcell.KeyEnter), want: []int{0}},
		{name: "k moves up", script: script{}.text("jk ").key(tcell.KeyEnter), want: []int{0}},
		{name: "G and End jump to the last row", script: script{}.text("G ").key(tcell.KeyHome).key(tcell.KeyEnd).text(" a").key(tcell.KeyEnd).text(" ").key(tcell.KeyEnter), want: []int{0, 1}},
		{name: "g and Home jump to the header", script: script{}.text("g ").key(tcell.KeyEnd).key(tcell.KeyHome).text("j ").key(tcell.KeyEnter), want: []int{1}},
		{name: "escape cancels a selection", script: script{}.text("a").key(tcell.KeyEscape), want: nil},
		{name: "q cancels", script: script{}.text(" q"), want: nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, _ := runPickerScript(t, 60, 12, tt.script)
			if !slices.Equal(got, tt.want) {
				t.Fatalf("expected %v, got %v", tt.want, got)
			}
		})
	}
}

func TestRunPicker_drawsTheSelectionAndCursor(t *testing.T) {
	_, frames := runPickerScript(t, 70, 12, script{}.text(" j").key(tcell.KeyEscape))
	f := frames[2]

	want := map[int]string{
		0:  " Select traces to open (1/3 selected)",
		2:  "  Group A (1/2)",
		3:  "    [x] a1",
		4:  "  > [ ] a2",
		5:  "  Group B (0/1)",
		6:  "    [ ] b1",
		11: " ↑/↓ move  space toggle  a all  n none  enter open  q/esc quit",
	}
	for y, line := range want {
		if got := f.row(y); got != line {
			t.Errorf("row %d: expected %q, got %q", y, line, got)
		}
	}
	if !hasAttr(f.style(4, 4), tcell.AttrUnderline) || hasAttr(f.style(4, 3), tcell.AttrUnderline) {
		t.Error("expected only the cursor row to be underlined")
	}
	if fg, _, _ := f.style(4, 3).Decompose(); fg != tcell.ColorGreen {
		t.Errorf("expected a green check mark, got %v", fg)
	}
}

func TestRunPicker_highlightsAHeaderUnderTheCursor(t *testing.T) {
	_, frames := runPickerScript(t, 60, 12, script{}.text("k").key(tcell.KeyEscape))

	if got := frames[1].row(2); got != "  Group A (0/2)" {
		t.Fatalf("expected the group header, got %q", got)
	}
	if !hasAttr(frames[1].style(2, 2), tcell.AttrReverse) {
		t.Error("expected the header under the cursor to be reversed")
	}
	if hasAttr(frames[0].style(2, 2), tcell.AttrReverse) {
		t.Error("expected the header not to be reversed without the cursor")
	}
}

func TestRunPicker_scrollsToKeepTheCursorVisible(t *testing.T) {
	// Height 6 leaves two list rows (2 and 3) for five entries, so a page is
	// two rows.
	sc := script{}.
		text("G").text("g").
		key(tcell.KeyPgDn).text("j").key(tcell.KeyPgDn).text(" ").
		key(tcell.KeyPgUp).text("k").key(tcell.KeyPgUp).text(" ").
		key(tcell.KeyEnter)
	got, frames := runPickerScript(t, 30, 6, sc)

	type view struct{ top, bottom string }
	rows := func(f frame) view {
		// The last column holds the scrollbar.
		return view{strings.TrimRight(f.lines[2][:29], " "), strings.TrimRight(f.lines[3][:29], " ")}
	}
	checks := []struct {
		frame int
		want  view
		thumb int // row of the scrollbar thumb
	}{
		{frame: 0, want: view{"  Group A (0/2)", "  > [ ] a1"}, thumb: 2},
		{frame: 1, want: view{"  Group B (0/1)", "  > [ ] b1"}, thumb: 3},
		{frame: 2, want: view{"  Group A (0/2)", "    [ ] a1"}, thumb: 2},
		{frame: 3, want: view{"    [ ] a1", "  > [ ] a2"}, thumb: 2},
		{frame: 4, want: view{"    [ ] a2", "  Group B (0/1)"}, thumb: 2},
		// PgDn from row 3 stops at the last row.
		{frame: 5, want: view{"  Group B (0/1)", "  > [ ] b1"}, thumb: 3},
		{frame: 7, want: view{"  > [ ] a2", "  Group B (1/1)"}, thumb: 2},
		{frame: 8, want: view{"  > [ ] a1", "    [ ] a2"}, thumb: 2},
		// PgUp from row 1 stops at the first row.
		{frame: 9, want: view{"  Group A (0/2)", "    [ ] a1"}, thumb: 2},
	}
	for _, c := range checks {
		f := frames[c.frame]
		if got := rows(f); got != c.want {
			t.Errorf("frame %d: expected %+v, got %+v", c.frame, c.want, got)
		}
		for y := 2; y <= 3; y++ {
			want := '│'
			if y == c.thumb {
				want = '┃'
			}
			if got := []rune(f.lines[y])[29]; got != want {
				t.Errorf("frame %d row %d: expected scrollbar %q, got %q", c.frame, y, want, got)
			}
		}
	}
	// The last space lands on the Group A header, so the whole group joins b1.
	if !slices.Equal(got, []int{0, 1, 2}) {
		t.Fatalf("expected [0 1 2], got %v", got)
	}
}

func TestRunPicker_keepsOneListRowOnATinyScreen(t *testing.T) {
	// Height 4 leaves no room between the header and footer lines; the list
	// still shows the cursor row.
	_, frames := runPickerScript(t, 30, 4, script{}.text("j").key(tcell.KeyEscape))

	if got := strings.TrimRight(frames[1].lines[2][:29], " "); got != "  > [ ] a2" {
		t.Fatalf("expected the cursor row a2, got %q", got)
	}
}

func TestRunPicker_redrawsAtTheNewSizeAfterAResize(t *testing.T) {
	got, frames := runPickerScript(t, 60, 12, script{}.resize(60, 5).text("G ").key(tcell.KeyEnter))
	if !slices.Equal(got, []int{2}) {
		t.Fatalf("expected [2], got %v", got)
	}

	f := frames[1]
	if len(f.lines) != 5 {
		t.Fatalf("expected a 5-row screen, got %d rows", len(f.lines))
	}
	if !strings.HasPrefix(f.row(4), " ↑/↓ move") {
		t.Errorf("expected the key help on the new last row, got %q", f.row(4))
	}
	// One list row remains, so jumping to the end scrolls b1 into it.
	if got := strings.TrimRight(frames[2].lines[2][:59], " "); got != "  > [ ] b1" {
		t.Errorf("expected b1 scrolled into view, got %q", got)
	}
}

func TestRunPicker_withoutGroupsOnlyQuits(t *testing.T) {
	got, frames := runPickerGroupsScript(t, 60, 12, nil, script{}.text("G").key(tcell.KeyEnter).text(" q"))
	if got != nil {
		t.Fatalf("expected nil, got %v", got)
	}
	if row := frames[1].row(0); row != " Select traces to open (0/0 selected)" {
		t.Errorf("expected an empty title count, got %q", row)
	}
}
