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
}

// NewDeps wires production dependencies.
func NewDeps(ios *iostreams.IOStreams, cliVersion string) Deps {
	return Deps{
		IOS:        ios,
		Runner:     dockercmd.ExecRunner{},
		Release:    release.NewClient(),
		CLIVersion: cliVersion,
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
	root  paths.InstallRoot
	lite  bool
	craft bool

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
	fmt.Fprintf(in.deps.IOS.Out, "✓ "+format+"\n", args...)
}

func (in *installer) infof(format string, args ...any) {
	fmt.Fprintf(in.deps.IOS.Out, "ℹ "+format+"\n", args...)
}

func (in *installer) warnf(format string, args ...any) {
	fmt.Fprintf(in.deps.IOS.Out, "⚠ "+format+"\n", args...)
}

func (in *installer) errorf(format string, args ...any) {
	fmt.Fprintf(in.deps.IOS.ErrOut, "✗ "+format+"\n", args...)
}

func (in *installer) plainf(format string, args ...any) {
	fmt.Fprintf(in.deps.IOS.Out, format+"\n", args...)
}

func (in *installer) stepf(title string) {
	in.step++
	fmt.Fprintf(in.deps.IOS.Out, "\n=== %s - Step %d/%d ===\n\n", title, in.step, in.totalSteps)
}
