package install

import (
	"context"
	"os"
	"path/filepath"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
)

// RunUninstall implements `deploy uninstall` (install.sh --delete-data):
// remove containers, volumes and the deployment directory. Destructive, so
// interactive runs must type DELETE; non-interactive runs require --force
// (install.sh refused non-interactive deletion outright).
func RunUninstall(ctx context.Context, deps Deps, opts Options) error {
	in := newInstaller(deps, opts)
	return in.runUninstall(ctx)
}

func (in *installer) runUninstall(ctx context.Context) error {
	in.root = paths.Resolve(in.opts.Dir)
	if len(in.root.Ambiguous) > 0 {
		return exitcodes.Newf(exitcodes.BadRequest,
			"multiple Onyx installs found (%s and %s) — pass --dir to pick one",
			in.root.Dir, in.root.Ambiguous[0])
	}
	if _, err := os.Stat(in.root.Dir); os.IsNotExist(err) {
		in.warnf("No Onyx data directory found at %s. Nothing to remove.", in.root.Dir)
		return nil
	}

	in.plainf("")
	in.plainf("=== WARNING: This will permanently delete all Onyx data ===")
	in.plainf("")
	in.warnf("This action will remove:")
	in.plainf("  • All Onyx containers and volumes")
	in.plainf("  • All files and configuration in %s", in.root.Dir)
	in.plainf("  • All user data and documents")
	in.plainf("")

	if in.opts.Force {
		in.infof("Proceeding without confirmation (--force).")
	} else {
		if in.prompt.AssumeDefaults {
			in.errorf("Cannot confirm destructive operation in non-interactive mode.")
			in.infof("Run interactively, pass --force, or remove %s manually.", in.root.Dir)
			return exitcodes.New(exitcodes.BadRequest, "uninstall requires confirmation")
		}
		ok, err := in.prompt.ConfirmTyped("Are you sure you want to continue? Type 'DELETE' to confirm: ", "DELETE")
		if err != nil {
			return err
		}
		in.plainf("")
		if !ok {
			in.infof("Operation cancelled.")
			return nil
		}
	}

	composeFile := filepath.Join(in.deploymentDir(), "docker-compose.yml")
	if _, err := os.Stat(composeFile); err == nil {
		if err := in.attachDockerCompose(ctx); err != nil {
			return err
		}
		in.infof("Removing Onyx containers and volumes...")
		cmd := in.compose.Command(in.deploymentDir(), stopFallbackEnv(), in.composeFileNames(true), "down", "-v")
		cmd.Stdout, cmd.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
		if _, err := in.deps.Runner.Run(ctx, cmd); err != nil {
			// Keep going like install.sh: the directory should still be
			// removable even when container cleanup fails.
			in.errorf("Failed to remove containers and volumes: %v", err)
		} else {
			in.successf("Onyx containers and volumes removed")
		}
	}

	in.infof("Removing data directories...")
	if err := os.RemoveAll(in.root.Dir); err != nil {
		return exitcodes.Newf(exitcodes.General, "failed to remove %s: %v", in.root.Dir, err)
	}
	in.successf("Data directories removed")
	in.plainf("")
	in.successf("All Onyx data has been permanently deleted!")
	return nil
}
