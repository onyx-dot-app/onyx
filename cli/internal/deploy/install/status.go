package install

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/ui"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
)

// Status is the machine-readable `deploy status --json` payload.
type Status struct {
	Installed    bool      `json:"installed"`
	Dir          string    `json:"dir"`
	Source       string    `json:"source"`
	ManifestTag  string    `json:"manifest_tag,omitempty"`
	EnvTag       string    `json:"env_tag,omitempty"`
	RunningTag   string    `json:"running_tag,omitempty"`
	Mode         string    `json:"mode,omitempty"`
	IncludeCraft bool      `json:"include_craft"`
	AccessURL    string    `json:"access_url,omitempty"`
	Services     []Service `json:"services"`
	Healthy      bool      `json:"healthy"`
}

// Service is one container of the deployment. The fields past Status are
// filled in only for containers in trouble, from `docker inspect`.
type Service struct {
	Name string `json:"name"`
	// Service is the compose service behind the container ("api_server"),
	// which is what the logs and compose commands take.
	Service   string `json:"service,omitempty"`
	Image     string `json:"image"`
	Status    string `json:"status"`
	Restarts  int    `json:"restarts,omitempty"`
	ExitCode  int    `json:"exit_code,omitempty"`
	OOMKilled bool   `json:"oom_killed,omitempty"`
	Diagnosis string `json:"diagnosis,omitempty"`
}

// name is what to call the service in a command or a sentence: the compose
// service when docker labelled it, the container otherwise.
func (s Service) name() string {
	if s.Service != "" {
		return s.Service
	}
	return s.Name
}

// RunStatus implements `deploy status`. Read-only: it never provisions or
// mutates anything. Exit codes make it usable as a probe: 0 when installed
// with all services up and none unhealthy, NotAvailable when no install
// exists, General when stopped or degraded.
func RunStatus(ctx context.Context, deps Deps, opts Options, jsonOut bool) error {
	in := newInstaller(deps, opts)
	return in.runStatus(ctx, jsonOut)
}

func (in *installer) runStatus(ctx context.Context, jsonOut bool) error {
	in.root = paths.Resolve(in.opts.Dir)
	st := Status{Dir: in.root.Dir, Source: string(in.root.Source)}

	if !paths.IsInstall(in.root.Dir) {
		if jsonOut {
			return in.emitStatus(st, exitcodes.NotAvailable)
		}
		in.infof("No Onyx install found at %s", in.root.Dir)
		for _, alt := range in.root.Ambiguous {
			in.infof("(another install exists at %s — pass --dir to inspect it)", alt)
		}
		in.infof("Install one with: %s", in.paint.Accent("onyx-cli deploy install"))
		return exitcodes.New(exitcodes.NotAvailable, "not installed")
	}
	st.Installed = true

	if manifest, err := state.Load(in.root.Dir); err != nil {
		in.warnf("%v", err)
	} else if manifest != nil {
		st.ManifestTag = manifest.InstalledTag
		st.Mode = string(manifest.Mode)
		st.IncludeCraft = manifest.IncludeCraft
	}
	if env, err := os.ReadFile(filepath.Join(in.deploymentDir(), ".env")); err == nil {
		st.EnvTag = Var(string(env), "IMAGE_TAG")
	}
	if st.Mode == "" {
		st.Mode = "standard"
		if in.overlayOnDisk(filepath.Base(deployfiles.LiteOverlay.DestRel)) {
			st.Mode = "lite"
		}
	}

	st.Services, st.RunningTag, st.AccessURL = in.inspectContainers(ctx)
	in.addFailureFacts(ctx, st.Services)

	up, unhealthy := 0, 0
	for _, s := range st.Services {
		if isRunning(s) {
			up++
		}
		if isUnhealthy(s) {
			unhealthy++
		}
	}
	st.Healthy = up > 0 && up == len(st.Services) && unhealthy == 0

	if jsonOut {
		code := exitcodes.Success
		if !st.Healthy {
			code = exitcodes.General
		}
		return in.emitStatus(st, code)
	}

	in.plainf("Onyx deployment at %s (%s)", st.Dir, st.Source)
	in.plainf("  Mode: %s%s", st.Mode, map[bool]string{true: " + craft", false: ""}[st.IncludeCraft])
	in.plainf("  Version (manifest): %s", in.orUnknown(st.ManifestTag))
	in.plainf("  Version (.env):     %s", in.orUnknown(st.EnvTag))
	in.plainf("  Version (running):  %s", in.orUnknown(st.RunningTag))
	if drift(st.ManifestTag, st.EnvTag, st.RunningTag) {
		in.warnf("Version drift detected — the manifest, .env, and running containers disagree.")
		in.infof("A restart applies .env: %s", in.paint.Accent("onyx-cli deploy stop && onyx-cli deploy install"))
	}
	in.plainf("")
	if len(st.Services) == 0 {
		in.infof("No containers found (deployment is stopped)")
		return exitcodes.New(exitcodes.General, "deployment is stopped")
	}
	for _, s := range st.Services {
		sev := severityOf(s.Status)
		line := fmt.Sprintf("  %s %-40s %s", sev.paint(in.paint, sev.mark()), s.Name, in.paintStatus(s.Status))
		if s.Restarts >= 2 {
			line += in.paint.Dim(fmt.Sprintf("  ·  %d restarts", s.Restarts))
		}
		in.plainf("%s", line)
	}
	in.plainf("")
	if st.AccessURL != "" {
		in.infof("Access Onyx at: %s", st.AccessURL)
	}
	if unhealthy > 0 {
		in.failf("%d of %d services unhealthy", unhealthy, len(st.Services))
		in.explainFailures(st.Services, isUnhealthy)
		return exitcodes.New(exitcodes.General, "deployment is degraded")
	}
	if up < len(st.Services) {
		in.failf("%d of %d containers are not running", len(st.Services)-up, len(st.Services))
		in.explainFailures(st.Services, notRunning)
		return exitcodes.New(exitcodes.General, "deployment is partially stopped")
	}
	in.successf("All %d services are up", up)
	return nil
}

func (in *installer) emitStatus(st Status, code exitcodes.Code) error {
	data, err := json.MarshalIndent(st, "", "  ")
	if err != nil {
		return err
	}
	fmt.Fprintln(in.deps.IOS.Out, string(data))
	if code == exitcodes.Success {
		return nil
	}
	return exitcodes.New(code, "see status output")
}

// inspectContainers lists the project's containers via the compose project
// label (the project name is pinned to "onyx" in the compose file, so this
// works regardless of directory names or which overlays are active).
func (in *installer) inspectContainers(ctx context.Context) (services []Service, runningTag, accessURL string) {
	if !dockercmd.Installed() {
		return nil, "", ""
	}
	in.docker.RefreshSudo(ctx)
	cmd := in.docker.Command(nil, "ps", "-a",
		"--filter", "label=com.docker.compose.project="+dockercmd.ProjectName,
		"--format", `{{.Names}}	{{.Image}}	{{.Status}}	{{.Ports}}	{{.Label "com.docker.compose.service"}}`)
	res, err := in.deps.Runner.Run(ctx, cmd)
	if err != nil {
		in.warnf("Could not query docker: %v", err)
		return nil, "", ""
	}
	for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
		if line == "" {
			continue
		}
		parts := strings.SplitN(line, "\t", 5)
		if len(parts) < 3 {
			continue
		}
		svc := Service{Name: parts[0], Image: parts[1], Status: parts[2]}
		if len(parts) == 5 {
			svc.Service = parts[4]
		}
		services = append(services, svc)
		// Only Onyx app images carry the deployment version; infrastructure
		// containers (nginx, postgres, redis, ...) have their own tags.
		if runningTag == "" && strings.HasPrefix(svc.Status, "Up") &&
			strings.Contains(svc.Image, "onyxdotapp/onyx") {
			if idx := strings.LastIndex(svc.Image, ":"); idx != -1 {
				runningTag = svc.Image[idx+1:]
			}
		}
		if accessURL == "" && len(parts) >= 4 && strings.HasPrefix(svc.Status, "Up") {
			if port := publishedHostPort(parts[3]); port != "" {
				accessURL = "http://localhost:" + port
			}
		}
	}
	return services, runningTag, accessURL
}

var hostPortPattern = regexp.MustCompile(`(?:0\.0\.0\.0|\[::\]|127\.0\.0\.1):(\d+)->`)

// publishedHostPort extracts the first published host port from a docker ps
// Ports column (e.g. "0.0.0.0:3000->80/tcp, [::]:3000->80/tcp").
func publishedHostPort(ports string) string {
	m := hostPortPattern.FindStringSubmatch(ports)
	if m == nil {
		return ""
	}
	return m[1]
}

// drift reports whether the known version numbers disagree (unknowns are
// skipped rather than counted as drift).
func drift(tags ...string) bool {
	known := ""
	for _, t := range tags {
		if t == "" {
			continue
		}
		if known == "" {
			known = t
			continue
		}
		if t != known {
			return true
		}
	}
	return false
}

// isRunning, isUnhealthy and notRunning are the tests the verdict counts
// with, so the sentences underneath it can be selected by the same rule the
// number was.
func isRunning(s Service) bool   { return strings.HasPrefix(s.Status, "Up") }
func notRunning(s Service) bool  { return !isRunning(s) }
func isUnhealthy(s Service) bool { return strings.Contains(s.Status, "(unhealthy)") }

// addFailureFacts fills in what `docker ps` left out, for the containers a
// verdict could end up reporting. Only those: the extra call costs a
// round-trip, and a service that is up and healthy has nothing to explain.
func (in *installer) addFailureFacts(ctx context.Context, services []Service) {
	var names []string
	for _, s := range services {
		if notRunning(s) || isUnhealthy(s) {
			names = append(names, s.Name)
		}
	}
	facts := in.inspectFacts(ctx, names)
	for i, s := range services {
		f, ok := facts[s.Name]
		if !ok {
			continue
		}
		services[i].Restarts = f.Restarts
		services[i].ExitCode = f.ExitCode
		services[i].OOMKilled = f.OOMKilled
		services[i].Diagnosis = f.diagnose(s.Status)
	}
}

// explainFailures says what is wrong with each service the verdict above it
// counted, and names the one command that shows why. Without it the worst
// state on the board — a container that keeps dying — is also the only one the
// report says nothing more about. troubled is the verdict's own test, so the
// report can't claim two failures and then explain one.
func (in *installer) explainFailures(services []Service, troubled func(Service) bool) {
	var names []string
	for _, s := range services {
		if !troubled(s) {
			continue
		}
		names = append(names, s.name())
		if s.Diagnosis != "" {
			in.plainf("  %s %s", s.name(), s.Diagnosis)
		}
	}
	if len(names) == 0 {
		return
	}
	// Past a handful of failing services the list stops being a command
	// worth pasting, and the whole deployment is the thing to look at.
	named := " " + strings.Join(names, " ")
	if len(names) > 3 {
		named = ""
	}
	in.infof("See why: %s", in.paint.Accent("onyx-cli deploy logs"+in.dirArg()+named))
}

// severity is how much attention one container's state deserves.
type severity int

const (
	sevOK severity = iota
	sevWatch
	sevBad
)

// severityOf reads a `docker ps` status through the same vocabulary the
// install watcher uses: green once the container is up for good, red when it
// is unhealthy or gone (a container restarting is crash-looping, not
// starting), yellow while it is still on its way to either.
func severityOf(status string) severity {
	switch healthDetail(status) {
	case "healthy", "running":
		return sevOK
	case "unhealthy", "exited", "dead", "restarting":
		return sevBad
	}
	return sevWatch // waiting, created, paused, and whatever docker adds next
}

func (s severity) paint(p ui.Painter, text string) string {
	switch s {
	case sevOK:
		return p.Ok(text)
	case sevBad:
		return p.Err(text)
	}
	return p.Warn(text)
}

// mark heads a service line, so a container in trouble stands out without
// color having to carry it alone — piped output, NO_COLOR, and readers who
// can't tell the two hues apart all still get the answer.
func (s severity) mark() string {
	switch s {
	case sevOK:
		return "✓"
	case sevBad:
		return "✗"
	}
	return "⚠"
}

var (
	// trailingHealth is the verdict docker appends to a running container's
	// status: "Up 5 minutes (healthy)", "(unhealthy)", "(health: starting)".
	trailingHealth = regexp.MustCompile(`\([^()]*\)$`)
	// leadingState is the state a stopped or looping container is in, with
	// the exit code that belongs to it: "Exited (137) 1 minute ago".
	leadingState = regexp.MustCompile(`^[A-Za-z]+( \(\d+\))?`)
)

// paintStatus colors what the status actually says about the container and
// dims the rest. Elapsed time reads the same whatever state it belongs to, so
// leaving it uncolored keeps the eye on the words that differ between lines.
func (in *installer) paintStatus(status string) string {
	sev := severityOf(status)
	if loc := trailingHealth.FindStringIndex(status); loc != nil {
		return in.paint.Dim(status[:loc[0]]) + sev.paint(in.paint, status[loc[0]:])
	}
	// A container with no health check to report is just up: the mark ahead
	// of it already says so, and coloring the word again only spends green on
	// the lines nobody needs to look at.
	if sev == sevOK {
		return in.paint.Dim(status)
	}
	// Nothing states the verdict, so the state itself carries it.
	if loc := leadingState.FindStringIndex(status); loc != nil {
		return sev.paint(in.paint, status[:loc[1]]) + in.paint.Dim(status[loc[1]:])
	}
	return status
}

func (in *installer) orUnknown(s string) string {
	if s == "" {
		return in.paint.Dim("unknown")
	}
	return s
}
