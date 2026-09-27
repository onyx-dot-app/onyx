package install

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/ui"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/version"
)

// RunUpgrade implements `deploy upgrade`: install.sh's "type 'update'"
// sub-flow promoted to a scriptable verb. Only the IMAGE_TAG line (plus
// SANDBOX_BACKEND when Craft is enabled) is rewritten in .env; managed files
// are refreshed to the target tag with user edits preserved via the manifest.
func RunUpgrade(ctx context.Context, deps Deps, opts Options) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	in := newInstaller(deps, opts)
	in.cancel = cancel
	err := in.runUpgrade(ctx)
	if errors.Is(err, ui.ErrAborted) || (err != nil && ctx.Err() != nil) {
		return exitcodes.New(exitcodes.General, "upgrade cancelled")
	}
	return err
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

	// --tag is checked before the wizard takes over the screen, so a typo
	// fails as a plain error instead of flashing the alt screen.
	pinnedTag := in.opts.Tag
	if pinnedTag != "" {
		validated, verr := in.validateTag(ctx, pinnedTag)
		if verr != nil {
			return verr
		}
		pinnedTag = validated
	}

	// Upgrades share the install wizard (dry runs stay line-oriented).
	if in.fancy() && !in.opts.DryRun {
		in.wiz = ui.StartWizard(in.deps.IOS.Out, "Onyx Upgrade", in.deps.CLIVersion, in.cancel)
		defer in.wiz.Abort()
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
	if errors.Is(err, os.ErrNotExist) {
		// Reachable when a fresh install failed before its first start: the
		// config files are there, but .env was rolled back.
		return exitcodes.Newf(exitcodes.NotAvailable,
			"no deployment/.env at %s — run `onyx-cli deploy install` to finish setting up this deployment", in.root.Dir)
	}
	if err != nil {
		return fmt.Errorf("failed to read %s: %w", envPath, err)
	}
	env := string(envBytes)
	installedTag := Var(env, "IMAGE_TAG")
	if installedTag == "" {
		installedTag = "edge"
	}

	// The deployment mode never changes on upgrade; recover it from the
	// manifest or the overlays on disk. --prod only asserts what is already
	// there (first adoption has no manifest to say so) — converting a
	// deployment that is recorded as something else is refused, because prod
	// needs TLS material and env files an upgrade cannot conjure.
	if in.opts.Prod && manifest.Mode != "" && manifest.Mode != state.ModeProd {
		return exitcodes.Newf(exitcodes.BadRequest,
			"this deployment is recorded as %s — upgrade cannot convert it to prod", manifest.Mode)
	}
	in.prod = in.opts.Prod || manifest.Mode == state.ModeProd ||
		in.overlayOnDisk(filepath.Base(deployfiles.ProdCompose.DestRel))
	in.lite = !in.prod && (manifest.Mode == state.ModeLite ||
		in.overlayOnDisk(filepath.Base(deployfiles.LiteOverlay.DestRel)))
	in.craft = in.opts.IncludeCraft || manifest.IncludeCraft ||
		in.overlayOnDisk(filepath.Base(deployfiles.CraftOverlay.DestRel))
	in.dev = !in.prod && (in.opts.Dev || manifest.Dev ||
		in.overlayOnDisk(filepath.Base(deployfiles.DevOverlay.DestRel)))
	in.resolveProject(manifest)
	if in.wiz != nil {
		mode := "Standard"
		switch {
		case in.lite:
			mode = "Lite"
		case in.prod && in.craft:
			mode = "Prod+Craft"
		case in.prod:
			mode = "Prod"
		case in.craft:
			mode = "Std+Craft"
		}
		if in.dev {
			mode += "+Dev"
		}
		in.wiz.Answer("Mode", mode)
		in.wiz.Answer("From", installedTag)
	}

	targetTag, err := in.resolveUpgradeTag(ctx, installedTag, pinnedTag)
	if err != nil {
		return err
	}
	if in.wiz != nil {
		in.wiz.Answer("To", targetTag)
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
		if in.localFiles() {
			in.plainf("  • Upgrade: %s → %s (config files: existing on disk, embedded copies for gaps)", installedTag, targetTag)
		} else {
			in.plainf("  • Upgrade: %s → %s (config ref: %s)", installedTag, targetTag, release.ConfigRef(targetTag))
		}
		craftNote := ""
		if in.craft {
			craftNote = ", Craft: true"
		}
		if in.dev {
			craftNote += ", Dev overlay: true"
		}
		in.plainf("  • Mode: %s%s", in.modeName(), craftNote)
		if name := in.composeOverrideName(); name != "" {
			in.plainf("  • Compose override: %s (yours, applied last)", name)
		}
		if in.project != dockercmd.DefaultProjectName {
			in.plainf("  • Compose project: %s", in.project)
		}
		in.plainf("")
		in.successf("Dry run complete (no changes made)")
		return nil
	}

	if err := in.resolveDockerProblems(ctx, in.gatherPreflight(ctx)); err != nil {
		return err
	}
	if err := in.checkComposeVersion(ctx); err != nil {
		return err
	}
	if !in.prod {
		in.observedPort = in.runningHostPort(ctx)
	}
	// The running services are deliberately NOT stopped here: `up` recreates
	// any container whose image or config changed, so the old version keeps
	// serving while images download, and a failed pull leaves it running
	// instead of a stopped half-upgraded stack.

	in.phase("Updating configuration")

	// Config files and the manifest are written before .env, and not the other
	// way round: .env is what names the deployment's version, so it must not
	// name the target until everything else that can still fail on disk has
	// succeeded. Otherwise a refresh or a save that fails here leaves the
	// deployment claiming a version it has not so much as pulled.
	configRef := ""
	if !in.localFiles() {
		configRef = release.ConfigRef(targetTag)
		in.infof("Refreshing config files to match %s...", configRef)
	}
	fetcher := &fileFetcher{in: in}
	if err := in.materializeFiles(ctx, configRef, managedFiles(in.prod, in.lite, in.craft, in.dev), manifest, fetcher); err != nil {
		return err
	}
	in.noteComposeOverride()

	if in.craft {
		in.ensureCraftResources(ctx)
	}

	// Persist the manifest's file records now: if the pull fails, the next
	// run must still know the freshly materialized files were CLI-written,
	// not hand-edited. InstalledTag advances only after a successful start.
	if err := manifest.Save(in.root.Dir); err != nil {
		return err
	}

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
	// Reuse the port the deployment already runs on — scanning for a free one
	// here would collide with our own still-running nginx and silently move
	// Onyx to another port. Installs created by install.sh never recorded
	// HOST_PORT, so fall back to the port they are publishing right now.
	// Prod skips all of it: the overlay publishes 80/443, HOST_PORT unread.
	hostPort := 0
	if !in.prod {
		var perr error
		hostPort, perr = strconv.Atoi(Var(env, "HOST_PORT"))
		if perr != nil {
			if hostPort = in.observedPort; hostPort == 0 {
				hostPort = 3000
			}
			env = SetVar(env, "HOST_PORT", strconv.Itoa(hostPort))
		}
	}
	if err := os.WriteFile(envPath, []byte(env), 0600); err != nil {
		return fmt.Errorf("failed to write .env: %w", err)
	}
	in.successf("Updated IMAGE_TAG to %s in .env file (all other settings preserved)", targetTag)

	if err := in.pullImages(ctx, targetTag, hostPort); err != nil {
		in.rollbackEnv(envPath, envBytes)
		return err
	}
	if err := in.startServices(ctx, targetTag, installedTag, hostPort); err != nil {
		return err
	}

	now := time.Now().UTC()
	manifest.InstalledTag = targetTag
	manifest.CLIVersion = in.deps.CLIVersion
	if manifest.Mode == "" {
		manifest.Mode = state.ModeStandard
		switch {
		case in.lite:
			manifest.Mode = state.ModeLite
		case in.prod:
			manifest.Mode = state.ModeProd
		}
	}
	in.recordProject(manifest)
	manifest.IncludeCraft = in.craft
	manifest.Dev = in.dev
	if !hadManifest || manifest.InstalledAt.IsZero() {
		manifest.InstalledAt = now
	}
	manifest.UpdatedAt = now
	if err := manifest.Save(in.root.Dir); err != nil {
		// The services are already up on the target: say what did happen, or
		// the error reads as an upgrade that never took place.
		return fmt.Errorf("upgraded to %s, but recording it in %s failed: %w", targetTag, state.FileName, err)
	}

	in.printUpgradeSuccess(hostPort, installedTag, targetTag)
	return nil
}

// printUpgradeSuccess mirrors printSuccess: a summary card when the wizard
// drives the run, plain lines otherwise.
func (in *installer) printUpgradeSuccess(hostPort int, from, to string) {
	url := fmt.Sprintf("http://localhost:%d", hostPort)
	if in.prod {
		url = in.prodAccessURL()
	}
	headline := fmt.Sprintf("Onyx upgraded: %s → %s", from, to)
	var tail []string
	if url != "" {
		tail = []string{"Access Onyx at: " + ui.Accent(url), ""}
	}
	tail = append(tail, manageLines()...)
	if in.wiz != nil {
		in.wiz.Stage(ui.StageComplete)
		in.wiz.Finish(append([]string{"🎉 " + headline, ""}, tail...)...)
		in.wiz = nil
		return
	}
	in.plainf("")
	in.successf("%s", headline)
	for _, l := range tail {
		in.plainf("%s", l)
	}
	in.plainf("")
}

// resolveUpgradeTag picks the target: the already-validated --tag, or the
// latest app release (prompted for interactively; taken as-is with
// --no-prompt), with the same edge fallback install.sh uses when the release
// lookup fails.
func (in *installer) resolveUpgradeTag(ctx context.Context, installedTag, pinnedTag string) (string, error) {
	if pinnedTag != "" {
		return pinnedTag, nil
	}
	defaultTag := ""
	if tag, err := in.latestAppTag(ctx); err == nil {
		defaultTag = tag
	} else {
		defaultTag = in.unreachableTagFallback(ctx)
	}
	if in.wiz == nil && !in.prompt.AssumeDefaults {
		in.infof("Currently installed: %s", installedTag)
	}
	return in.askVersion(ctx, "Version to upgrade to", defaultTag)
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
	if in.opts.AllowDowngrade {
		in.infof("Proceeding anyway (--allow-downgrade).")
		return nil
	}
	if in.prompt.AssumeDefaults {
		return exitcodes.New(exitcodes.BadRequest,
			"refusing to downgrade non-interactively — re-run with --allow-downgrade to override")
	}
	ok, err := in.confirmYN("Downgrade anyway?", false)
	if err != nil {
		return err
	}
	if !ok {
		return exitcodes.New(exitcodes.General, "upgrade cancelled")
	}
	return nil
}
