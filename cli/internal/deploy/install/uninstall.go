package install

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
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
	// The directory is about to be removed recursively, and --dir,
	// ONYX_DEPLOYMENT_DIR and the legacy INSTALL_PREFIX all name it freely, so
	// it has to both look like a deployment and be a directory whose entire
	// contents can be written off. Markers alone don't settle the second
	// question: a deployment/ under $HOME marks $HOME.
	if !paths.IsInstall(in.root.Dir) && !state.Exists(in.root.Dir) {
		return exitcodes.Newf(exitcodes.BadRequest,
			"%s doesn't look like an Onyx deployment (no deployment/docker-compose.yml, deployment/.env or %s) — refusing to delete it",
			in.root.Dir, state.FileName)
	}
	if err := paths.CheckDeletable(in.root.Dir); err != nil {
		return exitcodes.Newf(exitcodes.BadRequest,
			"refusing to delete everything under %s: %v — point --dir at the deployment directory itself, or remove it by hand if Onyx really lives there",
			in.root.Dir, err)
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
			in.errorf("Failed to remove containers and volumes: %v", err)
			// Deleting the directory now would strand the containers and
			// volumes with nothing left that describes them, so the files
			// stay put for a retry unless the user insists.
			if !in.opts.Force {
				return exitcodes.Newf(exitcodes.General,
					"containers or volumes are still present — %s was left in place so you can retry; pass --force to delete it anyway",
					in.root.Dir)
			}
			in.warnf("Deleting %s anyway (--force) — clean up leftovers with %s",
				in.root.Dir, in.paint.Accent(fmt.Sprintf("docker compose -p %s down -v", dockercmd.ProjectName)))
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
