package tui

import (
	"testing"
	"time"

	"github.com/gdamore/tcell/v2"
)

var testCols = []Column{
	{Key: "id", Title: "ID", Required: true},
	{Key: "note", Title: "Note"},
}

// runSim drives the editor on a simulation screen. InjectKey blocks until the
// event is consumed, so inject runs in its own goroutine concurrently with the
// editor loop; each key is paced by the loop's next PollEvent. The sequence must
// reach save or cancel so the loop terminates.
func runSim(t *testing.T, cols []Column, rows []map[string]string, inject func(s tcell.SimulationScreen)) ([]map[string]string, bool) {
	t.Helper()
	s := tcell.NewSimulationScreen("")
	if err := s.Init(); err != nil {
		t.Fatalf("SimulationScreen Init: %v", err)
	}
	defer s.Fini()
	s.SetSize(100, 30)

	type outcome struct {
		rows  []map[string]string
		saved bool
	}
	done := make(chan outcome, 1)
	go func() {
		r, sv := runEditor(s, "test", cols, rows)
		done <- outcome{r, sv}
	}()
	go inject(s)

	select {
	case o := <-done:
		return o.rows, o.saved
	case <-time.After(5 * time.Second):
		t.Fatal("editor did not terminate; injected sequence never reached save/cancel")
		return nil, false
	}
}

func typeRunes(s tcell.SimulationScreen, text string) {
	for _, r := range text {
		s.InjectKey(tcell.KeyRune, r, tcell.ModNone)
	}
}

func key(s tcell.SimulationScreen, k tcell.Key) {
	s.InjectKey(k, 0, tcell.ModNone)
}

func TestEditRowsAddAndSave(t *testing.T) {
	rows, saved := runSim(t, testCols, nil, func(s tcell.SimulationScreen) {
		typeRunes(s, "a") // add
		typeRunes(s, "GHSA-1")
		key(s, tcell.KeyTab)
		typeRunes(s, "hello")
		key(s, tcell.KeyEnter) // submit form
		typeRunes(s, "s")      // save
	})

	if !saved {
		t.Fatal("expected saved = true")
	}
	if len(rows) != 1 {
		t.Fatalf("expected 1 row, got %d: %#v", len(rows), rows)
	}
	if rows[0]["id"] != "GHSA-1" || rows[0]["note"] != "hello" {
		t.Fatalf("unexpected row: %#v", rows[0])
	}
}

func TestEditRowsCancelKeepsNothing(t *testing.T) {
	initial := []map[string]string{{"id": "KEEP", "note": ""}}
	rows, saved := runSim(t, testCols, initial, func(s tcell.SimulationScreen) {
		typeRunes(s, "q") // quit without saving
	})
	if saved {
		t.Fatal("expected saved = false on quit")
	}
	if len(rows) != 1 || rows[0]["id"] != "KEEP" {
		t.Fatalf("rows should be returned unchanged, got %#v", rows)
	}
}

func TestEditRowsValidationBlocksEmptyID(t *testing.T) {
	rows, saved := runSim(t, testCols, nil, func(s tcell.SimulationScreen) {
		typeRunes(s, "a")
		key(s, tcell.KeyEnter) // empty id -> rejected, stays in form
		typeRunes(s, "OK")
		key(s, tcell.KeyEnter) // now valid -> submits
		typeRunes(s, "s")
	})
	if !saved {
		t.Fatal("expected saved = true")
	}
	if len(rows) != 1 || rows[0]["id"] != "OK" {
		t.Fatalf("expected single row id=OK, got %#v", rows)
	}
}

func TestEditRowsTextEditingBackspace(t *testing.T) {
	rows, _ := runSim(t, testCols, nil, func(s tcell.SimulationScreen) {
		typeRunes(s, "a")
		typeRunes(s, "ABX")
		key(s, tcell.KeyBackspace2) // delete X -> AB
		typeRunes(s, "C")           // -> ABC
		key(s, tcell.KeyEnter)
		typeRunes(s, "s")
	})
	if len(rows) != 1 || rows[0]["id"] != "ABC" {
		t.Fatalf("expected id=ABC, got %#v", rows)
	}
}

func TestEditRowsDelete(t *testing.T) {
	initial := []map[string]string{
		{"id": "A", "note": ""},
		{"id": "B", "note": ""},
	}
	rows, saved := runSim(t, testCols, initial, func(s tcell.SimulationScreen) {
		typeRunes(s, "d") // delete row under cursor (A)
		typeRunes(s, "y") // confirm
		typeRunes(s, "s") // save
	})
	if !saved {
		t.Fatal("expected saved = true")
	}
	if len(rows) != 1 || rows[0]["id"] != "B" {
		t.Fatalf("expected single row id=B after deleting A, got %#v", rows)
	}
}
