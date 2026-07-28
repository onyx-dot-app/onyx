package install

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/resources"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/version"
)

// RunUpgrade implements `deploy upgrade`: install.sh's "type 'update'"
// sub-flow promoted to a scriptable verb. Only the IMAGE_TAG line (plus
// SANDBOX_BACKEND when Craft is enabled) is rewritten in .env; managed files
// are refreshed to the target tag with user edits preserved via the manifest.
func RunUpgrade(ctx context.Context, deps Deps, opts Options) error {
	in := newInstaller(deps, opts)
	in.totalSteps = 4
	return in.runUpgrade(ctx)
}

func (in *installer) runUpgrade(ctx context.Context) error {
	in.root = paths.Resolve(in.opts.Dir)
	if len(in.root.Ambiguous) > 0 {
		return exitcodes.Newf(exitcodes.BadRequest,
			"multiple Onyx installs found (%s and %s) — pass --dir to pick one",
			in.root.Dir, in.root.Ambiguous[0])
	}
	if !paths.IsInstall(in.root.Dir) {
		return exitcodes.Newf(exitcodes.NotAvailable,
			"no Onyx deployment found at %s — run `onyx-cli deploy install` first", in.root.Dir)
	}

	manifest, err := state.Load(in.root.Dir)
	if err != nil {
		return err
	}
	hadManifest := manifest != nil
	if manifest == nil {
		manifest = &state.Manifest{}
		in.infof("No %s found — adopting this install; files not written by the CLI are treated as potentially customized", state.FileName)
	}

	envPath := filepath.Join(in.root.Dir, "deployment", ".env")
	envBytes, err := os.ReadFile(envPath)
	if err != nil {
		return fmt.Errorf("failed to read %s: %w", envPath, err)
	}
	env := string(envBytes)
	installedTag := Var(env, "IMAGE_TAG")
	if installedTag == "" {
		installedTag = "edge"
	}

	// The deployment mode never changes on upgrade; recover it from the
	// manifest or the overlays on disk.
	in.lite = manifest.Mode == state.ModeLite ||
		in.overlayOnDisk(filepath.Base(deployfiles.LiteOverlay.DestRel))
	in.craft = in.opts.IncludeCraft || manifest.IncludeCraft ||
		in.overlayOnDisk(filepath.Base(deployfiles.CraftOverlay.DestRel))

	targetTag, err := in.resolveUpgradeTag(ctx, installedTag)
	if err != nil {
		return err
	}

	if err := in.downgradeGuard(installedTag, targetTag); err != nil {
		return err
	}

	// Future: surface breaking changes from the GitHub release notes for
	// every tag between installedTag and targetTag here, before any file is
	// touched.

	if in.opts.DryRun {
		in.infof("Dry run mode — showing what would happen:")
		in.plainf("  • Install root: %s (%s)", in.root.Dir, in.root.Source)
		in.plainf("  • Upgrade: %s → %s (config ref: %s)", installedTag, targetTag, release.ConfigRef(targetTag))
		in.plainf("  • Lite mode: %t, Craft: %t", in.lite, in.craft)
		in.plainf("")
		in.successf("Dry run complete (no changes made)")
		return nil
	}

	if err := in.ensureDockerAndCompose(ctx); err != nil {
		return err
	}
	if err := in.guardServicesStopped(ctx); err != nil {
		return err
	}

	in.stepf("Updating configuration")
	in.infof("Updating configuration for version %s...", targetTag)
	env = SetVar(env, "IMAGE_TAG", targetTag)
	if in.craft {
		if in.opts.IncludeCraft {
			env = SetVarUncomment(env, "ENABLE_CRAFT", "true")
		}
		backend := sandboxBackendForTag(targetTag)
		env = SetVarUncomment(env, "SANDBOX_BACKEND", backend)
		in.successf("Aligned SANDBOX_BACKEND=%s with image tag %s", backend, targetTag)
	}
	if err := os.WriteFile(envPath, []byte(env), 0600); err != nil {
		return fmt.Errorf("failed to write .env: %w", err)
	}
	in.successf("Updated IMAGE_TAG to %s in .env file (all other settings preserved)", targetTag)

	configRef := ""
	if !in.opts.Local {
		configRef = release.ConfigRef(targetTag)
		in.infof("Refreshing config files to match %s...", configRef)
	}
	fetcher := &fileFetcher{in: in}
	if err := in.materializeFiles(ctx, configRef, managedFiles(in.lite, in.craft), manifest, fetcher); err != nil {
		return err
	}

	if in.craft {
		in.ensureCraftResources(ctx)
	}

	hostPort := resources.FindAvailablePort(3000)
	if err := in.pullAndStart(ctx, targetTag, hostPort); err != nil {
		return err
	}

	now := time.Now().UTC()
	manifest.InstalledTag = targetTag
	manifest.CLIVersion = in.deps.CLIVersion
	if manifest.Mode == "" {
		manifest.Mode = state.ModeStandard
		if in.lite {
			manifest.Mode = state.ModeLite
		}
	}
	manifest.IncludeCraft = in.craft
	if !hadManifest || manifest.InstalledAt.IsZero() {
		manifest.InstalledAt = now
	}
	manifest.UpdatedAt = now
	if err := manifest.Save(in.root.Dir); err != nil {
		return err
	}

	in.stepf("Upgrade Complete!")
	in.plainf("")
	in.successf("Onyx upgraded: %s → %s", installedTag, targetTag)
	in.infof("Access Onyx at: http://localhost:%d", hostPort)
	in.infof("Check service health with: onyx-cli deploy status")
	in.plainf("")
	return nil
}

// resolveUpgradeTag picks the target: --tag, or the latest app release
// (prompted for interactively; taken as-is with --no-prompt), with the same
// edge fallback install.sh uses when the release lookup fails.
func (in *installer) resolveUpgradeTag(ctx context.Context, installedTag string) (string, error) {
	if in.opts.Tag != "" {
		return in.opts.Tag, nil
	}
	defaultTag := "edge"
	if tag, err := in.deps.Release.LatestAppTag(ctx); err == nil {
		defaultTag = tag
	} else {
		in.warnf("Could not determine latest Onyx release — falling back to edge")
	}
	if in.prompt.AssumeDefaults {
		return defaultTag, nil
	}
	in.infof("Currently installed: %s", installedTag)
	tag, err := in.prompt.Ask(fmt.Sprintf("Enter tag to upgrade to [default: %s]: ", defaultTag), defaultTag)
	if err != nil {
		return "", err
	}
	in.plainf("")
	return tag, nil
}

// downgradeGuard warns when both tags parse as semver and the target is
// older; floating and non-semver tags can't be ordered and pass silently.
func (in *installer) downgradeGuard(installedTag, targetTag string) error {
	installed, okInstalled := version.Parse(installedTag)
	target, okTarget := version.Parse(targetTag)
	if !okInstalled || !okTarget || !target.LessThan(installed) {
		return nil
	}
	in.warnf("Target %s is OLDER than the installed %s. Downgrades are not supported by Onyx and may corrupt data written by newer schema versions.", targetTag, installedTag)
	if in.opts.Force {
		in.infof("Proceeding anyway (--force).")
		return nil
	}
	if in.prompt.AssumeDefaults {
		return exitcodes.New(exitcodes.BadRequest,
			"refusing to downgrade non-interactively — re-run with --force to override")
	}
	ok, err := in.prompt.Confirm("Downgrade anyway? (y/N) ", false)
	if err != nil {
		return err
	}
	if !ok {
		return exitcodes.New(exitcodes.General, "upgrade cancelled")
	}
	return nil
}
