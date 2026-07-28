// Package install orchestrates the deploy lifecycle: install, upgrade, stop,
// status and uninstall of a docker compose Onyx deployment. It is the Go
// replacement for deployment/docker_compose/install.sh.
package install

import (
	"fmt"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/prompt"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/ui"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

// Options carries the flags shared across the deploy verbs. Flag names match
// install.sh so bootstrap passthrough keeps working.
type Options struct {
	Lite         bool
	IncludeCraft bool
	Tag          string
	Local        bool
	NoPrompt     bool
	DryRun       bool
	Verbose      bool
	NoWait       bool
	Dir          string
	Force        bool
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

	// Resolved during the run.
	root     paths.InstallRoot
	lite     bool
	craft    bool
	wiz      *ui.Wizard // live wizard when the fancy renderer drives the run
	cancel   func()     // cancels in-flight work when the wizard is quit
	rootless bool       // daemon runs rootless (limits what compose can grant)

	// step counter for the "=== title - Step N/M ===" headers.
	step, totalSteps int
}

func newInstaller(deps Deps, opts Options) *installer {
	return &installer{
		deps:   deps,
		opts:   opts,
		prompt: prompt.New(deps.IOS, opts.NoPrompt),
		docker: dockercmd.NewDocker(deps.Runner),
	}
}

// Output helpers mirroring install.sh's prefixes (plain text, no color).

func (in *installer) successf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("ok", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, "✓ "+format+"\n", args...)
}

func (in *installer) infof(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, "ℹ "+format+"\n", args...)
}

func (in *installer) warnf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("warn", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, "⚠ "+format+"\n", args...)
}

func (in *installer) errorf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("err", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.ErrOut, "✗ "+format+"\n", args...)
}

func (in *installer) plainf(format string, args ...any) {
	if in.wiz != nil {
		in.wiz.Note("", fmt.Sprintf(format, args...))
		return
	}
	fmt.Fprintf(in.deps.IOS.Out, format+"\n", args...)
}

func (in *installer) stepf(title string) {
	in.step++
	fmt.Fprintf(in.deps.IOS.Out, "\n=== %s - Step %d/%d ===\n\n", title, in.step, in.totalSteps)
}

// fancy reports whether the interactive renderer drives this run (never
// under --no-prompt, so scripted output stays line-oriented).
func (in *installer) fancy() bool {
	return in.deps.Fancy && !in.opts.NoPrompt
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
	return in.prompt.Confirm(question+" ", defaultYes)
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
