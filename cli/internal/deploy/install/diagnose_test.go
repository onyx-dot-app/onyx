package install

import (
	"strings"
	"testing"
)

// The whole point of a diagnosis is that the reader doesn't have to know what
// a docker exit code, a restart count, or an empty health log means.
func TestDiagnoseNamesTheFailure(t *testing.T) {
	probe := &health{Status: "unhealthy", FailingStreak: 4, Log: []healthProbe{
		{ExitCode: 0, Output: "ok"},
		{ExitCode: 1, Output: "curl: (7) Failed to connect to localhost port 8080\nafter 0 ms\n"},
	}}
	cases := []struct {
		name   string
		facts  containerFacts
		status string
		want   string
	}{{
		// Memory is the one failure the user can fix without reading a log,
		// and 137 alone doesn't say it.
		name:   "out of memory",
		facts:  containerFacts{Restarts: 5, ExitCode: 137, OOMKilled: true},
		status: "Exited (137) 1 minute ago",
		want:   "ran out of memory",
	}, {
		name:   "crash loop",
		facts:  containerFacts{Restarts: 18, ExitCode: 255},
		status: "Restarting (255) 13 seconds ago",
		want:   "has restarted 18 times (exit 255) — it is crash-looping",
	}, {
		name:   "failing health check quotes its own output",
		facts:  containerFacts{Health: probe},
		status: "Up 5 minutes (unhealthy)",
		want:   "curl: (7) Failed to connect to localhost port 8080",
	}, {
		// One restart is a daemon restart or a one-off kill, not a loop.
		name:   "stopped cleanly",
		facts:  containerFacts{Restarts: 1},
		status: "Exited (0) 2 hours ago",
		want:   "exit 0 — a clean shutdown",
	}, {
		name:   "nothing to add",
		facts:  containerFacts{},
		status: "Up 5 minutes (healthy)",
		want:   "",
	}}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := c.facts.diagnose(c.status)
			if c.want == "" {
				if got != "" {
					t.Errorf("diagnose(%q) = %q, want nothing", c.status, got)
				}
				return
			}
			if !strings.Contains(got, c.want) {
				t.Errorf("diagnose(%q) = %q, want it to mention %q", c.status, got, c.want)
			}
		})
	}
}

// A stack trace or a page of probe output would push the rest of the report
// off the screen.
func TestFirstLineStaysOnOneLine(t *testing.T) {
	got := firstLine("  boom: it broke  \nstack frame 1\nstack frame 2\n")
	if got != "boom: it broke" {
		t.Errorf("firstLine = %q", got)
	}
	if long := firstLine(strings.Repeat("x", 500)); len(long) > 130 || !strings.HasSuffix(long, "…") {
		t.Errorf("long message not trimmed: %d chars, %q", len(long), long)
	}
}
