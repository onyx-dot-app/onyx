package install

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// containerFacts is what `docker inspect` knows about a container that
// `docker ps` does not: how often it has been restarted, how it exited, and
// what its health check last said. A status line can't tell a service that is
// still coming up from one that has died twenty times — these numbers can.
type containerFacts struct {
	Name      string  `json:"name"`
	Restarts  int     `json:"restarts"`
	ExitCode  int     `json:"exit"`
	OOMKilled bool    `json:"oom"`
	Error     string  `json:"error"`
	Health    *health `json:"health"`
}

type health struct {
	Status        string
	FailingStreak int
	Log           []healthProbe
}

// healthProbe is one run of a container's health check, as docker records it.
type healthProbe struct {
	ExitCode int
	Output   string
}

// inspectFormat renders one JSON object per container. Health is emitted
// whole: docker keeps only the last few probe results, and their output is
// the closest thing to an explanation a failing health check ever gives.
const inspectFormat = `{"name":{{json .Name}},"restarts":{{.RestartCount}},` +
	`"exit":{{.State.ExitCode}},"oom":{{.State.OOMKilled}},"error":{{json .State.Error}},` +
	`"health":{{if .State.Health}}{{json .State.Health}}{{else}}null{{end}}}`

// inspectFacts asks docker about the named containers in one call. A docker
// that refuses simply leaves the extra detail out of the report — every
// caller degrades to what `docker ps` already said.
func (in *installer) inspectFacts(ctx context.Context, names []string) map[string]containerFacts {
	if len(names) == 0 {
		return nil
	}
	args := append([]string{"inspect", "--format", inspectFormat}, names...)
	res, err := in.deps.Runner.Run(ctx, in.docker.Command(nil, args...))
	if err != nil {
		return nil
	}
	facts := make(map[string]containerFacts, len(names))
	for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
		var f containerFacts
		if json.Unmarshal([]byte(line), &f) != nil {
			continue
		}
		// Inspect names containers with a leading slash; ps doesn't.
		f.Name = strings.TrimPrefix(f.Name, "/")
		facts[f.Name] = f
	}
	return facts
}

// crashLoop is the restart count past which a container is failing to start
// rather than being restarted for an ordinary reason (a daemon restart, a
// one-off kill).
const crashLoop = 3

// diagnose says what went wrong in the words a user can act on. It reads the
// facts against the `docker ps` status they came with, and returns "" when
// nothing it knows adds to what the status line already showed.
func (f containerFacts) diagnose(status string) string {
	switch {
	case f.OOMKilled:
		return "ran out of memory and was killed — give Docker more memory, or reinstall with --lite"
	case f.Error != "":
		return "could not start: " + firstLine(f.Error)
	case f.Restarts >= crashLoop:
		return fmt.Sprintf("has restarted %d times (%s) — it is crash-looping, not starting",
			f.Restarts, exitReason(f.ExitCode))
	case f.probe() != "":
		return "is running, but its health check keeps failing: " + f.probe()
	case strings.Contains(status, "(unhealthy)"):
		return "is running, but its health check is failing"
	case strings.HasPrefix(status, "Created"):
		// Compose creates a container before starting it, so this is a start
		// that never happened — usually because what it waits on never became
		// healthy. It has no logs of its own to read.
		return "was created but never started"
	case strings.HasPrefix(status, "Exited"), strings.HasPrefix(status, "Restarting"):
		return fmt.Sprintf("is not running (%s)", exitReason(f.ExitCode))
	}
	return ""
}

// probe is the output of the last health check that failed, on one line.
func (f containerFacts) probe() string {
	if f.Health == nil {
		return ""
	}
	for i := len(f.Health.Log) - 1; i >= 0; i-- {
		if entry := f.Health.Log[i]; entry.ExitCode != 0 {
			return firstLine(entry.Output)
		}
	}
	return ""
}

// exitReason translates the exit codes a container dies with. 137 and 143 are
// the ones worth naming: both are signals rather than the app's own choice,
// and 137 is what a memory limit looks like from the outside.
func exitReason(code int) string {
	switch code {
	case 0:
		return "exit 0 — a clean shutdown"
	case 137:
		return "exit 137 — killed, usually by a memory limit"
	case 143:
		return "exit 143 — stopped by a signal"
	}
	return fmt.Sprintf("exit %d", code)
}

// firstLine trims a message to its first line, so a stack trace or a wall of
// health-check output can't take over the report.
func firstLine(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, '\n'); i != -1 {
		s = strings.TrimSpace(s[:i])
	}
	const maxLen = 120
	if len(s) > maxLen {
		s = strings.TrimSpace(s[:maxLen]) + "…"
	}
	return s
}
