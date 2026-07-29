package ui

import (
	"strings"
	"testing"
	"time"

	"github.com/charmbracelet/x/ansi"
)

// sampleModels covers the panes that carry the widest content: a question with
// long hints, and a running phase with a per-service checklist.
func sampleModels() map[string]wizModel {
	began := time.Now().Add(-42 * time.Second)
	return map[string]wizModel{
		"question": {
			title:   "Onyx Installer",
			version: "v0.1.0",
			stage:   StageConfigure,
			answers: []answerMsg{{"Version", "v4.4.6"}},
			sel: &askSelectMsg{
				title: "Onyx is already running. Applying this configuration restarts its services.",
				opts: []Option{
					{Label: "Continue", Hint: "keeps serving while images download; each service restarts once, at the end"},
					{Label: "Cancel", Hint: "leave everything running"},
				},
			},
			notes: []noteMsg{{"ok", "Deployment files are up to date"}},
		},
		"task": {
			title:      "Onyx Installer",
			version:    "v0.1.0",
			stage:      StagePull,
			answers:    []answerMsg{{"Action", "Upgrade"}, {"Version", "v4.4.6"}},
			taskLabel:  "Pulling images",
			taskExtra:  "3/9 images · 1.2 GB / 4.8 GB",
			taskActive: true,
			taskBegan:  began,
			services: []ServiceRow{
				{Name: "backend", Ready: true},
				{Name: "web_server", Detail: "62%  310.4 MB / 500.1 MB"},
				{Name: "model_server", Detail: "4%  21.0 MB / 512.5 MB"},
				{Name: "relational_db", Detail: "waiting for health"},
			},
			notes: []noteMsg{{"", "Using deployment/.env from the existing install"}},
		},
	}
}

// The wizard has to fit the terminal it was given: anything wider wraps and
// smears the full-screen layout across lines.
func TestViewFitsTerminalWidth(t *testing.T) {
	sizes := []struct{ w, h int }{{40, 12}, {52, 16}, {64, 20}, {80, 24}, {120, 40}}
	for name, base := range sampleModels() {
		for _, size := range sizes {
			m := base
			m.width, m.height = size.w, size.h
			lines := strings.Split(m.View().Content, "\n")
			for i, line := range lines {
				if got := ansi.StringWidthWc(line); got > size.w {
					t.Errorf("%s at %dx%d: line %d is %d columns wide:\n%s",
						name, size.w, size.h, i+1, got, line)
				}
			}
			if len(lines) > size.h {
				t.Errorf("%s at %dx%d: view is %d lines tall", name, size.w, size.h, len(lines))
			}
		}
	}
}

// A download note that no longer fits sheds whole parts: cutting it mid-figure
// would leave a unit-less number on screen.
func TestNarrowChecklistKeepsPercent(t *testing.T) {
	m := sampleModels()["task"]
	m.width, m.height = 64, 24
	content := m.View().Content
	if !strings.Contains(content, "62%") {
		t.Errorf("the percentage should outlive the byte figures:\n%s", content)
	}
	if strings.Contains(content, "310.4") {
		t.Errorf("byte figures should be dropped whole, not clipped:\n%s", content)
	}
}

// Long option hints must survive a narrow screen, wrapped under their option
// rather than truncated away.
func TestNarrowViewKeepsOptionHints(t *testing.T) {
	m := sampleModels()["question"]
	m.width, m.height = 44, 20
	content := m.View().Content
	if !strings.Contains(content, "restarts once") {
		t.Errorf("hint text was dropped at 44 columns:\n%s", content)
	}
	if !strings.Contains(content, "Step 1/4") {
		t.Errorf("the rail should collapse to a step line below %d columns:\n%s", minTwoColumn, content)
	}
}
