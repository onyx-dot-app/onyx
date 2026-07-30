// Package install orchestrates the deploy lifecycle: install, upgrade, stop,
// status and uninstall of a docker compose Onyx deployment. It is the Go
// replacement for deployment/docker_compose/install.sh.
package install

import (
	"fmt"
	"io"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/prompt"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/ui"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

// Options carries the flags shared across the deploy verbs. Flag names match
// install.sh so bootstrap passthrough keeps working.
type Options struct {
	Lite         bool
	IncludeCraft bool
	Prod         bool
	Dev          bool
	Tag          string
	Local        bool
	Offline      bool
	NoPrompt     bool
	DryRun       bool
	Verbose      bool
	NoWait       bool
	Dir          string
	// Project overrides the docker compose project name (default: the one
	// recorded in the manifest, else "onyx").
	Project string
	Force   bool
	// AllowDowngrade proceeds when the target version is older than the
	// installed one. Deliberately separate from Force: a scripted rollback
	// must not also have to opt into overwriting hand-edited files.
	AllowDowngrade bool
}

// Deps carries the injectable collaborators (fakes in tests).
type Deps struct {
	IOS        *iostreams.IOStreams
	Runner     dockercmd.Runner
	Release    *release.Client
	CLIVersion string
	// Fancy enables the Bubble Tea prompts and live progress. Off in tests
	// and whenever a real TTY isn't driving the run.
	Fancy bool
}

// NewDeps wires production dependencies.
func NewDeps(ios *iostreams.IOStreams, cliVersion string) Deps {
	return Deps{
		IOS:        ios,
		Runner:     dockercmd.ExecRunner{},
		Release:    release.NewClient(),
		CLIVersion: cliVersion,
		Fancy:      ui.Enabled(ios),
	}
}

// installer bundles the state threaded through one verb invocation.
type installer struct {
	deps    Deps
	opts    Options
	prompt  *prompt.Prompter
	docker  *dockercmd.Docker
	compose *dockercmd.Compose
	paint   ui.Painter

	// Resolved during the run.
	root     paths.InstallRoot
	lite     bool
	craft    bool
	prod     bool
	dev      bool
	project  string     // compose project name every docker/compose call uses
	wiz      *ui.Wizard // live wizard when the fancy renderer drives the run
	cancel   func()     // cancels in-flight work when the wizard is quit
	rootless bool       // daemon runs rootless (limits what compose can grant)

	// observedPort is the host port the deployment published when the run
	// started (0 if it wasn't running). It recovers the port of installs
	// that predate recording HOST_PORT in .env.
	observedPort int
	// wasLite records that the deployment was in lite mode when the run
	// started, so a switch to standard can undo lite's .env adjustments.
	wasLite bool
	// forceRecreate records that services were already running when the run
	// started, and that this run may replace them; `up` gets --force-recreate
	// so every service ends up on the new configuration.
	forceRecreate bool
}

func newInstaller(deps Deps, opts Options) *installer {
	return &installer{
		deps:   deps,
		opts:   opts,
		prompt: prompt.New(deps.IOS, opts.NoPrompt),
		docker: dockercmd.NewDocker(deps.Runner),
		paint:  ui.NewPainter(deps.IOS),
	}
}

// Output helpers mirroring install.sh's prefixes. Only the mark is colored,
// the way the wizard colors its notes, so the text stays readable on any
// background and unstyled when the output isn't a terminal.

func (in *installer) successf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("ok", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, in.paint.Ok("✓ ")+format+"\n", args...)
}

func (in *installer) infof(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, in.paint.Dim("ℹ ")+format+"\n", args...)
}

func (in *installer) warnf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("warn", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, in.paint.Warn("⚠ ")+format+"\n", args...)
}

func (in *installer) errorf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("err", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.ErrOut, in.paint.Err("✗ ")+format+"\n", args...)
}

// failf is errorf's report-side twin: the same mark, but on stdout, for a
// verb whose failure IS the output that was asked for (status), where
// splitting the verdict from the list it explains would leave both halves
// unreadable on their own.
func (in *installer) failf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("err", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, in.paint.Err("✗ ")+format+"\n", args...)
}

// resolveProject settles the compose project name for this run: the --project
// flag, then the name recorded in the manifest (nil is fine), then the
// default pinned in docker-compose.yml. Mirrored onto the compose handle when
// one is already attached; attach points set it for the other order.
func (in *installer) resolveProject(manifest *state.Manifest) {
	switch {
	case in.opts.Project != "":
		in.project = in.opts.Project
	case manifest != nil && manifest.Project != "":
		in.project = manifest.Project
	default:
		in.project = dockercmd.DefaultProjectName
	}
	if in.compose != nil {
		in.compose.Project = in.project
	}
}

// projectName is the compose project this run operates on, safe to call
// before resolveProject has run.
func (in *installer) projectName() string {
	if in.project != "" {
		return in.project
	}
	return dockercmd.DefaultProjectName
}

// resolveProjectFromDisk resolves the project for verbs that don't otherwise
// load the manifest (stop, logs, uninstall). A manifest that can't be read
// resolves to the defaults rather than blocking a verb that may be the fix.
func (in *installer) resolveProjectFromDisk() {
	manifest, err := state.Load(in.root.Dir)
	if err != nil {
		in.warnf("%v", err)
	}
	in.resolveProject(manifest)
}

// modeName names the resolved deployment mode the way the manifest records it.
func (in *installer) modeName() string {
	switch {
	case in.prod:
		return string(state.ModeProd)
	case in.lite:
		return string(state.ModeLite)
	}
	return string(state.ModeStandard)
}

// localFiles reports whether config files come from disk and the embedded
// copies rather than GitHub. --offline implies it: a run that promises to
// touch no network cannot go and fetch them.
func (in *installer) localFiles() bool {
	return in.opts.Local || in.opts.Offline
}

// dirArg repeats the --dir this run was given, so a command the output
// suggests still points at the same deployment when it isn't the default one.
func (in *installer) dirArg() string {
	if in.opts.Dir == "" {
		return ""
	}
	return fmt.Sprintf(" --dir %q", in.opts.Dir)
}

func (in *installer) plainf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, format+"\n", args...)
}

// cmdf prints a command on a line of its own, in the accent the summary card
// marks the URL with. These lines exist to be typed: what introduced them is
// prose, and the eye should be able to find the part that isn't.
func (in *installer) cmdf(format string, args ...any) {
	in.plainf("  %s", ui.Accent(fmt.Sprintf(format, args...)))
}

// fancy reports whether the interactive renderer drives this run (never
// under --no-prompt, so scripted output stays line-oriented, and never under
// --verbose, which streams compose's own output to the normal screen — under
// the alt screen it would be written where nothing can read it).
func (in *installer) fancy() bool {
	return in.deps.Fancy && !in.opts.NoPrompt && !in.opts.Verbose
}

// selectOne asks a single choice: arrow-key select when fancy, a numbered
// line prompt otherwise, the default when non-interactive.
func (in *installer) selectOne(title string, options []ui.Option, defaultIdx int) (int, error) {
	if in.prompt.AssumeDefaults {
		return defaultIdx, nil
	}
	if in.wiz != nil {
		return in.wiz.Select(title, options, defaultIdx)
	}
	in.infof("%s", title)
	for i, o := range options {
		marker := " "
		if i == defaultIdx {
			marker = "*"
		}
		in.plainf("  %s %d) %s%s", marker, i+1, o.Label, map[bool]string{true: " — " + o.Hint, false: ""}[o.Hint != ""])
	}
	answer, err := in.prompt.Ask(fmt.Sprintf("Choose an option [default: %d]: ", defaultIdx+1), fmt.Sprintf("%d", defaultIdx+1))
	if err != nil {
		return 0, err
	}
	for i := range options {
		if answer == fmt.Sprintf("%d", i+1) {
			return i, nil
		}
	}
	return defaultIdx, nil
}

// askString asks a free-form value with a prefilled default.
func (in *installer) askString(title, defaultVal string) (string, error) {
	if in.prompt.AssumeDefaults {
		return defaultVal, nil
	}
	if in.wiz != nil {
		return in.wiz.Input(title, defaultVal)
	}
	return in.prompt.Ask(fmt.Sprintf("%s [default: %s]: ", title, defaultVal), defaultVal)
}

// confirmYN asks a yes/no question (select when fancy).
func (in *installer) confirmYN(question string, defaultYes bool) (bool, error) {
	if in.prompt.AssumeDefaults {
		return defaultYes, nil
	}
	if in.wiz != nil {
		def := 1
		if defaultYes {
			def = 0
		}
		idx, err := in.wiz.Select(question, []ui.Option{{Label: "Yes"}, {Label: "No"}}, def)
		return idx == 0, err
	}
	hint := " (y/N) "
	if defaultYes {
		hint = " (Y/n) "
	}
	return in.prompt.Confirm(question+hint, defaultYes)
}

// phase prints a plain phase header (the wizard's rail replaces it when the
// fancy renderer is active).
func (in *installer) phase(title string) {
	if in.wiz != nil {
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, "\n— %s —\n", title)
}

// suspend hands the terminal back to fn when the wizard is live (sudo
// password prompts, provisioning output).
func (in *installer) suspend(fn func() error) error {
	if in.wiz != nil {
		return in.wiz.Suspend(fn)
	}
	return fn()
}

// runTask shows fn as a spinner phase rather than releasing the screen for it,
// for steps that neither prompt nor report progress worth reading — the only
// two things suspend() buys. Their narration ("Waiting for X to start...",
// once every couple of seconds) is what the spinner and its elapsed counter
// say instead, so under the wizard it is dropped rather than written to a
// screen the wizard has taken over.
func (in *installer) runTask(label string, fn func(progress io.Writer) error) error {
	if in.wiz == nil || in.opts.Verbose {
		in.infof("%s...", label)
		return fn(in.deps.IOS.Out)
	}
	in.wiz.TaskStart(label)
	err := fn(io.Discard)
	in.wiz.TaskDone(err == nil)
	return err
}
