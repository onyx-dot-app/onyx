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
	Dev          bool      `json:"dev"`
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
// with every service settled and up, NotAvailable when no install exists,
// General when stopped, degraded, or still coming up.
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

	manifest, err := state.Load(in.root.Dir)
	if err != nil {
		in.warnf("%v", err)
	} else if manifest != nil {
		st.ManifestTag = manifest.InstalledTag
		st.Mode = string(manifest.Mode)
		st.IncludeCraft = manifest.IncludeCraft
		st.Dev = manifest.Dev
	}
	in.resolveProject(manifest)
	if env, err := os.ReadFile(filepath.Join(in.deploymentDir(), ".env")); err == nil {
		st.EnvTag = Var(string(env), "IMAGE_TAG")
	}
	if st.Mode == "" {
		st.Mode = string(state.ModeStandard)
		switch {
		case in.overlayOnDisk(filepath.Base(deployfiles.LiteOverlay.DestRel)):
			st.Mode = string(state.ModeLite)
		case in.overlayOnDisk(filepath.Base(deployfiles.ProdCompose.DestRel)):
			st.Mode = string(state.ModeProd)
		}
	}
	// The overlay on disk is what the lifecycle verbs stack, manifest or not.
	st.Dev = st.Dev || in.overlayOnDisk(filepath.Base(deployfiles.DevOverlay.DestRel))

	st.Services, st.RunningTag, st.AccessURL = in.inspectContainers(ctx)
	// Prod publishes 80/443 behind a real domain; the port-derived localhost
	// URL is not where anyone reaches it.
	if st.Mode == string(state.ModeProd) {
		st.AccessURL = in.prodAccessURL()
	}
	in.addFailureFacts(ctx, st.Services)

	up, starting, failing := 0, 0, 0
	for _, s := range st.Services {
		switch s.severity() {
		case sevOK:
			up++
		case sevWatch:
			starting++
		default:
			failing++
		}
	}
	st.Healthy = up > 0 && up == len(st.Services)

	if jsonOut {
		code := exitcodes.Success
		if !st.Healthy {
			code = exitcodes.General
		}
		return in.emitStatus(st, code)
	}

	in.plainf("Onyx deployment at %s (%s)", st.Dir, st.Source)
	in.plainf("  Mode: %s%s%s", st.Mode,
		map[bool]string{true: " + craft", false: ""}[st.IncludeCraft],
		map[bool]string{true: " + dev", false: ""}[st.Dev])
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
		sev := s.severity()
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
	// One count, one list: every service that isn't up is worth naming,
	// whichever way it isn't. Splitting the verdict by kind used to drop the
	// rest of them — and a service still working through its health check was
	// counted as up, which is where a crash-looping container sampled between
	// two restarts went missing.
	if notUp := starting + failing; notUp > 0 {
		if failing > 0 {
			in.failf("%d of %d services are not up", notUp, len(st.Services))
		} else {
			in.warnf("%d of %d services are still starting", notUp, len(st.Services))
		}
		in.explainFailures(st.Services)
		return exitcodes.New(exitcodes.General, notUpReason(st.Services))
	}
	in.successf("All %d services are up", up)
	return nil
}

// notUpReason names the worst thing on the board, which is what the one-line
// reason a probe reads should say: a health check that is failing outranks a
// container that is missing, and both outrank a deployment that simply hasn't
// finished coming up.
func notUpReason(services []Service) string {
	stopped, looping := false, false
	for _, s := range services {
		switch {
		case isUnhealthy(s):
			return "deployment is degraded"
		case notRunning(s):
			stopped = true
		case s.crashLooping():
			looping = true
		}
	}
	switch {
	case stopped:
		return "deployment is partially stopped"
	case looping:
		return "deployment is degraded"
	}
	return "deployment is still starting"
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
// label (pinned in the compose file, or the recorded/--project override), so
// this works regardless of directory names or which overlays are active.
func (in *installer) inspectContainers(ctx context.Context) (services []Service, runningTag, accessURL string) {
	if !dockercmd.Installed() {
		return nil, "", ""
	}
	in.docker.RefreshSudo(ctx)
	cmd := in.docker.Command(nil, "ps", "-a",
		"--filter", "label=com.docker.compose.project="+in.projectName(),
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

// severity is how much attention this service deserves, reading the restart
// count `docker ps` doesn't show: a container past the crash-loop threshold is
// failing whatever state this sample caught it in.
//
// The restart count only settles an unsettled container, though. It counts the
// restarts the policy has had to perform over the whole life of the container
// and never goes back down, so one that looped at boot and has served for
// hours since is up, and says so.
func (s Service) severity() severity {
	if s.crashLooping() && unsettled(s.Status) {
		return sevBad
	}
	return severityOf(s.Status)
}

func (s Service) crashLooping() bool { return s.Restarts >= crashLoop }

// justStarted matches the uptimes docker prints for a container that came up
// moments ago: "Up Less than a second", "Up 3 seconds", "Up About a minute".
var justStarted = regexp.MustCompile(`^Up (Less than a second|\d+ seconds?|About a minute)`)

// unsettled reports whether `docker ps` alone can't call this container up: it
// is in no state to serve, or it is in one it entered moments ago. The second
// half is what a crash loop looks like between two restarts — a service with
// no health check to fail reads as a plain "Up 2 seconds" there, which is also
// how it reads when it is simply new, and only the restart count tells those
// apart.
func unsettled(status string) bool {
	return severityOf(status) != sevOK || justStarted.MatchString(status)
}

// isUp, isUnhealthy and notRunning are the tests the verdict counts with, so
// the sentences underneath it can be selected by the same rule the number was.
// A container is up once it has settled: one still inside its health check's
// start period has not, whatever the "Up" in front of its status says.
func isUp(s Service) bool        { return s.severity() == sevOK }
func notRunning(s Service) bool  { return !strings.HasPrefix(s.Status, "Up") }
func isUnhealthy(s Service) bool { return strings.Contains(s.Status, "(unhealthy)") }

// addFailureFacts fills in what `docker ps` left out, for the containers its
// listing couldn't settle on its own. Only those: the extra call costs a
// round-trip, and a service that has been serving for hours has nothing to
// explain. It selects on the status alone — the facts it fetches are what the
// fact-aware tests above read, so it cannot ask them.
func (in *installer) addFailureFacts(ctx context.Context, services []Service) {
	var names []string
	for _, s := range services {
		if unsettled(s.Status) {
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
// report says nothing more about. It selects on isUp, the verdict's own test,
// so the report can't claim two failures and then explain one.
func (in *installer) explainFailures(services []Service) {
	var names []string
	coming := true
	for _, s := range services {
		if isUp(s) {
			continue
		}
		names = append(names, s.name())
		coming = coming && s.severity() == sevWatch
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
	// Nothing has gone wrong when every one of them is still coming up, so the
	// command to offer is the one that watches them finish.
	if coming {
		in.infof("Follow along: %s", in.paint.Accent("onyx-cli deploy logs -f"+in.dirArg()+named))
		return
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
