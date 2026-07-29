package install

import (
	"context"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
)

// LogOptions carries the flags of `deploy logs`, which are passed through to
// compose rather than reinterpreted.
type LogOptions struct {
	// Services limits the output to these compose services (all when empty).
	Services []string
	Follow   bool
	Tail     string
	Since    string
}

// RunLogs implements `deploy logs`. It exists so triaging a service doesn't
// start with finding the deployment directory and remembering which overlays
// it was installed with — the same auto-detection stop and status already do.
func RunLogs(ctx context.Context, deps Deps, opts Options, logOpts LogOptions) error {
	in := newInstaller(deps, opts)
	return in.runLogs(ctx, logOpts)
}

func (in *installer) runLogs(ctx context.Context, l LogOptions) error {
	in.root = paths.Resolve(in.opts.Dir)
	if !paths.IsInstall(in.root.Dir) {
		in.infof("No Onyx install found at %s", in.root.Dir)
		for _, alt := range in.root.Ambiguous {
			in.infof("(another install exists at %s — pass --dir to read its logs)", alt)
		}
		return exitcodes.New(exitcodes.NotAvailable, "not installed")
	}
	if err := in.attachDockerCompose(ctx); err != nil {
		return err
	}

	args := []string{"logs"}
	if l.Follow {
		args = append(args, "--follow")
	}
	if l.Tail != "" {
		args = append(args, "--tail", l.Tail)
	}
	if l.Since != "" {
		args = append(args, "--since", l.Since)
	}
	args = append(args, l.Services...)

	// Same fallback env as stop: compose needs HOST_PORT/IMAGE_TAG to resolve
	// the files, not to read logs, so a half-written .env can't block triage.
	cmd := in.compose.Command(in.deploymentDir(), stopFallbackEnv(), in.composeFileNames(true), args...)
	cmd.Stdout, cmd.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
	if _, err := in.deps.Runner.Run(ctx, cmd); err != nil {
		// Ctrl-C is how a --follow ends, not a failure to report.
		if ctx.Err() != nil {
			return nil
		}
		return exitcodes.Newf(exitcodes.General, "docker compose logs failed: %v", err)
	}
	return nil
}
