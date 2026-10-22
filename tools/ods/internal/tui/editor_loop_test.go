package tui

import (
	"errors"
	"fmt"
	"strings"
	"testing"

	"github.com/gdamore/tcell/v2"
)

func runEditorScript(t *testing.T, w, h int, cols []Column, rows []map[string]string, sc script) ([]map[string]string, bool, []frame) {
	t.Helper()
	var got []map[string]string
	var saved bool
	frames := runScripted(t, w, h, sc, func(screen tcell.Screen) {
		got, saved = runEditor(screen, "test", cols, rows)
	})
	return got, saved, frames
}

func idRows(ids ...string) []map[string]string {
	rows := make([]map[string]string, len(ids))
	for i, id := range ids {
		rows[i] = map[string]string{"id": id, "note": ""}
	}
	return rows
}

func ids(rows []map[string]string) []string {
	out := make([]string, len(rows))
	for i, r := range rows {
		out[i] = r["id"]
	}
	return out
}

func TestRunEditor_editsTheRowUnderTheCursor(t *testing.T) {
	tests := []struct {
		name string
		move script
		want int
	}{
		{name: "down", move: script{}.key(tcell.KeyDown), want: 1},
		{name: "down then up", move: script{}.key(tcell.KeyDown).key(tcell.KeyDown).key(tcell.KeyUp), want: 1},
		{name: "j then k", move: script{}.text("jjk"), want: 1},
		{name: "end", move: script{}.key(tcell.KeyEnd), want: 3},
		{name: "G", move: script{}.text("G"), want: 3},
		{name: "home", move: script{}.key(tcell.KeyEnd).key(tcell.KeyHome), want: 0},
		{name: "g", move: script{}.text("Gg"), want: 0},
		{name: "page down stops at the last row", move: script{}.key(tcell.KeyPgDn), want: 3},
		{name: "page up stops at the first row", move: script{}.key(tcell.KeyEnd).key(tcell.KeyPgUp), want: 0},
	}
	for _, tt := range tests {
		for _, editKey := range []string{"e", "enter"} {
			t.Run(tt.name+" with "+editKey, func(t *testing.T) {
				sc := append(script{}, tt.move...)
				if editKey == "e" {
					sc = sc.text("e")
				} else {
					sc = sc.key(tcell.KeyEnter)
				}
				sc = sc.text("!").key(tcell.KeyEnter).text("s")

				got, saved, _ := runEditorScript(t, 100, 30, testCols, idRows("R0", "R1", "R2", "R3"), sc)
				if !saved {
					t.Fatal("expected saved = true")
				}
				want := []string{"R0", "R1", "R2", "R3"}
				want[tt.want] += "!"
				if fmt.Sprint(ids(got)) != fmt.Sprint(want) {
					t.Fatalf("expected %v, got %v", want, ids(got))
				}
			})
		}
	}
}

func TestRunEditor_ignoresEditAndDeleteWithoutRows(t *testing.T) {
	// If e, enter or d opened a form or prompt, "s" would not save.
	got, saved, frames := runEditorScript(t, 100, 30, testCols, nil, script{}.text("e").key(tcell.KeyEnter).text("ds"))
	if !saved || len(got) != 0 {
		t.Fatalf("expected an empty saved table, got saved=%t rows=%v", saved, got)
	}
	if row := frames[0].row(4); row != "  (no entries — press 'a' to add)" {
		t.Errorf("expected the empty-table hint, got %q", row)
	}
	if row := frames[0].row(0); row != " test  (0 entries)" {
		t.Errorf("expected the title with the count, got %q", row)
	}
}

func TestRunEditor_cancelLeavesTheCallerRowsUntouched(t *testing.T) {
	for _, cancel := range []tcell.Key{tcell.KeyEscape, tcell.KeyCtrlC} {
		t.Run(tcell.KeyNames[cancel], func(t *testing.T) {
			initial := idRows("A")
			sc := script{}.text("eZ").key(tcell.KeyEnter).key(cancel)

			_, saved, _ := runEditorScript(t, 100, 30, testCols, initial, sc)
			if saved {
				t.Fatal("expected saved = false")
			}
			if initial[0]["id"] != "A" {
				t.Fatalf("expected the caller's row to stay %q, got %q", "A", initial[0]["id"])
			}
		})
	}
}

func TestRunEditor_formCancelDiscardsTheChanges(t *testing.T) {
	sc := script{}.text("eZZ").key(tcell.KeyEscape).
		text("aNEW").key(tcell.KeyCtrlC).
		text("s")

	got, saved, _ := runEditorScript(t, 100, 30, testCols, idRows("A"), sc)
	if !saved {
		t.Fatal("expected saved = true")
	}
	if len(got) != 1 || got[0]["id"] != "A" {
		t.Fatalf("expected only the unchanged row A, got %v", got)
	}
}

func TestRunEditor_formEditingKeys(t *testing.T) {
	sc := script{}.text("a").
		text("ac").key(tcell.KeyLeft).text("b").                         // abc
		key(tcell.KeyHome).key(tcell.KeyLeft).text("x").                 // xabc
		key(tcell.KeyEnd).key(tcell.KeyRight).text("y").                 // xabcy
		key(tcell.KeyHome).key(tcell.KeyDelete).                         // abcy
		key(tcell.KeyRight).key(tcell.KeyRight).key(tcell.KeyBackspace). // acy
		key(tcell.KeyHome).key(tcell.KeyBackspace).                      // no-op at the start
		key(tcell.KeyEnd).key(tcell.KeyDelete).                          // no-op at the end
		key(tcell.KeyTab).text("n").                                     // note: n
		key(tcell.KeyBacktab).text("1").                                 // id: acy1, caret back at the end
		key(tcell.KeyDown).text("2").                                    // note: n2
		key(tcell.KeyUp).text("3").                                      // id: acy13
		key(tcell.KeyTab).key(tcell.KeyTab).text("4").                   // Tab wraps to id: acy134
		key(tcell.KeyBacktab).key(tcell.KeyBacktab).text("5").           // Backtab wraps to id: acy1345
		key(tcell.KeyEnter).text("s")

	got, saved, _ := runEditorScript(t, 100, 30, testCols, nil, sc)
	if !saved || len(got) != 1 {
		t.Fatalf("expected one saved row, got saved=%t rows=%v", saved, got)
	}
	if got[0]["id"] != "acy1345" || got[0]["note"] != "n2" {
		t.Fatalf("expected id=%q note=%q, got %v", "acy1345", "n2", got[0])
	}
}

func TestRunEditor_formPrefillsDefaultsAndShowsTheCaret(t *testing.T) {
	cols := []Column{
		{Key: "id", Title: "ID", Required: true},
		{Key: "note", Title: "Note", Default: "todo"},
	}
	sc := script{}.text("aX").key(tcell.KeyLeft).key(tcell.KeyEscape).text("q")

	_, _, frames := runEditorScript(t, 100, 30, cols, nil, sc)
	f := frames[2] // after typing X

	// Labels pad to the widest title, then " * : " or "   : ".
	if row := f.row(2); row != "  ID   * : X" {
		t.Errorf("expected the required id field, got %q", row)
	}
	if row := f.row(3); row != "  Note   : todo" {
		t.Errorf("expected the note default, got %q", row)
	}
	if !f.cursorVisible || f.cursorX != 12 || f.cursorY != 2 {
		t.Errorf("expected the caret after X at (12, 2), got (%d, %d) visible=%t", f.cursorX, f.cursorY, f.cursorVisible)
	}
	if fg, _, _ := f.style(2, 2).Decompose(); fg != tcell.ColorTeal {
		t.Errorf("expected the active label in teal, got %v", fg)
	}
	if got := frames[3]; got.cursorX != 11 {
		t.Errorf("expected Left to move the caret to 11, got %d", got.cursorX)
	}
}

func TestRunEditor_formShowsValidationErrorsUntilTheFieldChanges(t *testing.T) {
	cols := []Column{
		{Key: "id", Title: "ID", Required: true},
		{Key: "note", Title: "Note", Validate: func(v string) error {
			if !strings.HasPrefix(v, "#") {
				return errors.New("must start with #")
			}
			return nil
		}},
	}
	sc := script{}.
		text("a").key(tcell.KeyEnter).
		key(tcell.KeyTab).
		text("x").key(tcell.KeyBacktab).text("I").key(tcell.KeyEnter).
		key(tcell.KeyDown).key(tcell.KeyHome).text("#").key(tcell.KeyEnter).
		text("s")
	// Frame 2 follows the empty submit, frame 3 the Tab, frame 7 the submit
	// with an invalid note.

	got, saved, frames := runEditorScript(t, 100, 30, cols, nil, sc)
	if !saved || len(got) != 1 || got[0]["id"] != "I" || got[0]["note"] != "#x" {
		t.Fatalf("expected one saved row id=I note=#x, got saved=%t rows=%v", saved, got)
	}

	// The error line sits one blank row below the two fields.
	const errRow = 5
	if row := frames[2].row(errRow); row != "  ID is required" {
		t.Errorf("expected the required error, got %q", row)
	}
	if fg, _, _ := frames[2].style(2, errRow).Decompose(); fg != tcell.ColorRed {
		t.Errorf("expected the error in red, got %v", fg)
	}
	if row := frames[3].row(errRow); row != "" {
		t.Errorf("expected Tab to clear the error, got %q", row)
	}
	if row := frames[7].row(errRow); row != "  Note: must start with #" {
		t.Errorf("expected the validator error, got %q", row)
	}
}

func TestRunEditor_deleteAsksForConfirmation(t *testing.T) {
	tests := []struct {
		name   string
		answer script
		want   []string
	}{
		{name: "y deletes", answer: script{}.text("y"), want: []string{"B"}},
		{name: "Y deletes", answer: script{}.text("Y"), want: []string{"B"}},
		{name: "n keeps", answer: script{}.text("n"), want: []string{"A", "B"}},
		{name: "N keeps", answer: script{}.text("N"), want: []string{"A", "B"}},
		{name: "enter keeps", answer: script{}.key(tcell.KeyEnter), want: []string{"A", "B"}},
		{name: "escape keeps", answer: script{}.key(tcell.KeyEscape), want: []string{"A", "B"}},
		{name: "other keys wait for an answer", answer: script{}.text("xs").key(tcell.KeyCtrlC), want: []string{"A", "B"}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sc := append(script{}.text("d"), tt.answer...).text("s")

			got, saved, frames := runEditorScript(t, 100, 30, testCols, idRows("A", "B"), sc)
			if !saved {
				t.Fatal("expected saved = true")
			}
			if fmt.Sprint(ids(got)) != fmt.Sprint(tt.want) {
				t.Fatalf("expected %v, got %v", tt.want, ids(got))
			}
			if row := frames[1].row(29); row != ` Delete entry "A"?  (y/N)` {
				t.Errorf("expected the prompt on the last row, got %q", row)
			}
		})
	}
}

func TestRunEditor_deletingTheLastRowMovesTheCursorUp(t *testing.T) {
	sc := script{}.text("Gdy").text("e!").key(tcell.KeyEnter).text("s")

	got, _, _ := runEditorScript(t, 100, 30, testCols, idRows("A", "B"), sc)
	if fmt.Sprint(ids(got)) != "[A!]" {
		t.Fatalf("expected [A!], got %v", ids(got))
	}
}

func TestRunEditor_deleteWithoutColumnsHasAnEmptyLabel(t *testing.T) {
	got, saved, frames := runEditorScript(t, 100, 30, nil, []map[string]string{{}}, script{}.text("dys"))
	if !saved || len(got) != 0 {
		t.Fatalf("expected the row deleted, got saved=%t rows=%v", saved, got)
	}
	if row := frames[1].row(29); row != ` Delete entry ""?  (y/N)` {
		t.Errorf("expected an empty label in the prompt, got %q", row)
	}
}

func TestRunEditor_scrollsToKeepTheCursorVisible(t *testing.T) {
	// Height 9 leaves three table rows (4 to 6) for six entries.
	sc := script{}.text("G").text("g").key(tcell.KeyPgDn).key(tcell.KeyPgUp).text("q")
	_, _, frames := runEditorScript(t, 40, 9, testCols, idRows("R0", "R1", "R2", "R3", "R4", "R5"), sc)

	checks := []struct {
		frame int
		want  [3]string
		thumb int
	}{
		{frame: 0, want: [3]string{"> R0", "  R1", "  R2"}, thumb: 4},
		{frame: 1, want: [3]string{"  R3", "  R4", "> R5"}, thumb: 5},
		{frame: 2, want: [3]string{"> R0", "  R1", "  R2"}, thumb: 4},
		{frame: 3, want: [3]string{"  R1", "  R2", "> R3"}, thumb: 4},
		{frame: 4, want: [3]string{"> R0", "  R1", "  R2"}, thumb: 4},
	}
	for _, c := range checks {
		f := frames[c.frame]
		for i, want := range c.want {
			y := 4 + i
			// Cut the scrollbar column before comparing the cells.
			if got := strings.TrimRight(f.lines[y][:39], " "); got != want {
				t.Errorf("frame %d row %d: expected %q, got %q", c.frame, y, want, got)
			}
			wantBar := '│'
			if y == c.thumb {
				wantBar = '┃'
			}
			if got := []rune(f.lines[y])[39]; got != wantBar {
				t.Errorf("frame %d row %d: expected scrollbar %q, got %q", c.frame, y, wantBar, got)
			}
		}
	}
	if row := frames[0].row(0); row != " test  (6 entries)" {
		t.Errorf("expected the title with the count, got %q", row)
	}
}

func TestRunEditor_redrawsAtTheNewSizeAfterAResize(t *testing.T) {
	// Resize once in the table (frame 1), the form (frame 3) and the delete
	// prompt (frame 6).
	sc := script{}.
		resize(60, 10).
		text("e").resize(60, 8).key(tcell.KeyEscape).
		text("d").resize(60, 7).text("y").
		text("s")

	got, saved, frames := runEditorScript(t, 100, 30, testCols, idRows("A"), sc)
	if !saved || len(got) != 0 {
		t.Fatalf("expected the row deleted and saved, got saved=%t rows=%v", saved, got)
	}

	checks := []struct {
		frame  int
		height int
		prefix string
	}{
		{frame: 1, height: 10, prefix: " ↑/↓ move  a add"},
		{frame: 3, height: 8, prefix: " Tab/↑↓ field"},
		{frame: 6, height: 7, prefix: ` Delete entry "A"?`},
	}
	for _, c := range checks {
		f := frames[c.frame]
		if len(f.lines) != c.height {
			t.Fatalf("frame %d: expected %d rows, got %d", c.frame, c.height, len(f.lines))
		}
		if got := f.row(c.height - 1); !strings.HasPrefix(got, c.prefix) {
			t.Errorf("frame %d: expected the last row to start with %q, got %q", c.frame, c.prefix, got)
		}
	}
}
