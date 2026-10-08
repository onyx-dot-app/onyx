package tui

import (
	"strings"
	"testing"
	"time"

	"github.com/gdamore/tcell/v2"
)

// step produces the next event for a scripted screen. It runs on the loop's
// goroutine at the moment the loop polls, so it can change the screen first.
type step func(s tcell.SimulationScreen) tcell.Event

// script is an ordered list of events, built with the chainable helpers below.
type script []step

func (sc script) key(k tcell.Key) script {
	return append(sc, func(tcell.SimulationScreen) tcell.Event {
		return tcell.NewEventKey(k, 0, tcell.ModNone)
	})
}

func (sc script) text(text string) script {
	for _, r := range text {
		sc = append(sc, func(tcell.SimulationScreen) tcell.Event {
			return tcell.NewEventKey(tcell.KeyRune, r, tcell.ModNone)
		})
	}
	return sc
}

func (sc script) resize(w, h int) script {
	return append(sc, func(s tcell.SimulationScreen) tcell.Event {
		s.SetSize(w, h)
		return tcell.NewEventResize(w, h)
	})
}

func (sc script) event(ev tcell.Event) script {
	return append(sc, func(tcell.SimulationScreen) tcell.Event { return ev })
}

// frame is what the screen showed while the loop waited for an event.
type frame struct {
	lines         []string
	styles        [][]tcell.Style
	cursorX       int
	cursorY       int
	cursorVisible bool
}

// row returns line y without trailing spaces.
func (f frame) row(y int) string {
	return strings.TrimRight(f.lines[y], " ")
}

func (f frame) style(x, y int) tcell.Style {
	return f.styles[y][x]
}

// scriptedScreen feeds a script to the loop instead of a real input queue, and
// records a frame before each event. Events never go through the simulation
// screen's own channel, so no goroutine has to pace the input.
type scriptedScreen struct {
	tcell.SimulationScreen
	steps   script
	frames  []frame
	overrun bool
}

func (s *scriptedScreen) PollEvent() tcell.Event {
	s.frames = append(s.frames, s.snapshot())
	if len(s.steps) == 0 {
		// Escape unwinds every loop, so a script that ends too early fails
		// the test instead of hanging it.
		s.overrun = true
		return tcell.NewEventKey(tcell.KeyEscape, 0, tcell.ModNone)
	}
	next := s.steps[0]
	s.steps = s.steps[1:]
	return next(s.SimulationScreen)
}

func (s *scriptedScreen) snapshot() frame {
	cells, w, h := s.GetContents()
	f := frame{lines: make([]string, h), styles: make([][]tcell.Style, h)}
	for y := 0; y < h; y++ {
		var b strings.Builder
		f.styles[y] = make([]tcell.Style, w)
		for x := 0; x < w; x++ {
			c := cells[y*w+x]
			if len(c.Runes) > 0 {
				b.WriteRune(c.Runes[0])
			} else {
				b.WriteRune(' ')
			}
			f.styles[y][x] = c.Style
		}
		f.lines[y] = b.String()
	}
	f.cursorX, f.cursorY, f.cursorVisible = s.GetCursor()
	return f
}

// runScripted runs loop on a fresh w×h simulation screen fed by sc and returns
// the recorded frames: frames[i] is the screen shown before step i. The script
// must make the loop return by its last step.
func runScripted(t *testing.T, w, h int, sc script, loop func(screen tcell.Screen)) []frame {
	t.Helper()
	sim := tcell.NewSimulationScreen("")
	if err := sim.Init(); err != nil {
		t.Fatalf("SimulationScreen Init: %v", err)
	}
	defer sim.Fini()
	sim.SetSize(w, h)

	screen := &scriptedScreen{SimulationScreen: sim, steps: sc}
	done := make(chan struct{})
	go func() {
		defer close(done)
		loop(screen)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("loop did not return within 5s")
	}
	if screen.overrun {
		t.Fatalf("loop was still running after the script's %d steps", len(sc))
	}
	if len(screen.frames) != len(sc) {
		t.Fatalf("expected the loop to return on the last step, but it consumed %d of %d", len(screen.frames), len(sc))
	}
	return screen.frames
}

func hasAttr(style tcell.Style, attr tcell.AttrMask) bool {
	_, _, attrs := style.Decompose()
	return attrs&attr != 0
}
