package install

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/resources"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/ui"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/version"
)

// Resource expectations (halved thresholds in lite mode), from install.sh.
const (
	expectedRAMGB      = 10
	expectedDiskGB     = 32
	expectedRAMGBLite  = 4
	expectedDiskGBLite = 16

	waitTimeoutSeconds = 600
	minComposeVersion  = "2.24.0"
	failureLogTail     = 30

	// dockerDesktopWait bounds the wait for the macOS daemon to answer, and so
	// also bounds how long its spinner can turn with nothing else on screen.
	dockerDesktopWait = 120 * time.Second

	// s3FilestoreProfile is the COMPOSE_PROFILES entry that runs MinIO: on in
	// standard mode, off in lite. It is the only entry the CLI owns.
	s3FilestoreProfile = "s3-filestore"
)

// preflight carries the environment facts gathered concurrently while the
// user answers the setup questions. Healthy values stay quiet; only problems
// surface as warnings or provisioning offers.
// tagLookup carries the background release lookup's outcome. The error is
// reported by the receiving goroutine, not the sender: the output helpers
// drive the wizard, which only the main goroutine may touch.
type tagLookup struct {
	tag string
	err error
}

type preflight struct {
	dockerVersion  string
	composeVersion string
	composeType    string
	memoryMB       int
	diskGB         int
	rootless       bool
}

// RunInstall implements `deploy install` (and the install-onyx alias): fresh
// installs, and restart/update runs against an existing deployment.
func RunInstall(ctx context.Context, deps Deps, opts Options) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	in := newInstaller(deps, opts)
	in.cancel = cancel
	in.lite = opts.Lite
	in.craft = opts.IncludeCraft
	in.prod = opts.Prod
	in.dev = opts.Dev
	err := in.runInstall(ctx)
	if errors.Is(err, ui.ErrAborted) || (err != nil && ctx.Err() != nil) {
		return exitcodes.New(exitcodes.General, "installation cancelled")
	}
	return err
}

func (in *installer) runInstall(ctx context.Context) error {
	if in.opts.Lite && in.opts.IncludeCraft {
		return exitcodes.New(exitcodes.BadRequest,
			"--lite and --include-craft cannot be used together: Craft requires services (OpenSearch, Redis, background workers) that lite mode disables")
	}
	if in.opts.Prod && in.opts.Lite {
		return exitcodes.New(exitcodes.BadRequest,
			"--prod and --lite cannot be used together: they select conflicting compose files")
	}
	if in.opts.Prod && in.opts.Dev {
		return exitcodes.New(exitcodes.BadRequest,
			"--prod and --dev cannot be used together: the dev overlay publishes Postgres, Redis, OpenSearch and the API on the host, which a production deployment keeps behind nginx")
	}

	in.root = paths.Resolve(in.opts.Dir)
	envPath := filepath.Join(in.deploymentDir(), ".env")
	_, envErr := os.Stat(envPath)
	rerun := envErr == nil

	// Prod deployments are adopted or restarted, never created here: a fresh
	// one needs a filled-in .env, a .env.nginx naming the domain, and TLS
	// material from init-letsencrypt.sh before compose can as much as render.
	if in.opts.Prod && !rerun {
		return exitcodes.Newf(exitcodes.BadRequest,
			"no deployment/.env at %s — prod mode manages an existing production deployment; set one up per deployment/docker_compose/docker-compose.prod.yml first, then adopt it with `onyx-cli deploy upgrade --prod --dir %s`",
			in.root.Dir, in.root.Dir)
	}

	// --tag is checked before anything else runs: a typo must fail here, not
	// minutes later as a pull error with the bad version already on disk.
	// pinnedTag is assigned once, before the goroutines below read it, and
	// never again — opts stays immutable for the rest of the run.
	pinnedTag := in.opts.Tag
	if pinnedTag != "" {
		validated, verr := in.validateTag(ctx, pinnedTag)
		if verr != nil {
			return verr
		}
		pinnedTag = validated
	}

	// The latest-release lookup and the environment checks run in the
	// background while the user answers the questions below.
	tagCh := make(chan tagLookup, 1)
	go func() {
		switch {
		case in.opts.Offline && pinnedTag == "":
			// Deliberately not "edge": offline, the only deployable versions
			// are the ones whose images are already here. errOffline routes
			// this through the same fallback an unreachable GitHub takes.
			tagCh <- tagLookup{err: errOffline}
		case in.opts.Local:
			tagCh <- tagLookup{tag: "edge"}
		case pinnedTag != "":
			tagCh <- tagLookup{tag: pinnedTag}
		default:
			tag, err := in.deps.Release.LatestAppTag(ctx)
			tagCh <- tagLookup{tag: tag, err: err}
		}
	}()

	// tagCh delivers exactly one value; latestTag memoizes it so every
	// consumer (question defaults, initialTag) can read it safely. The
	// fallback is reported here rather than in the goroutine: output helpers
	// touch the wizard, which only the main goroutine may drive.
	var latestTag string
	getLatestTag := func() string {
		if latestTag == "" {
			got := <-tagCh
			if got.err != nil {
				got.tag = in.unreachableTagFallback(ctx)
			}
			latestTag = got.tag
		}
		return latestTag
	}

	if in.opts.DryRun {
		in.printPlan(getLatestTag())
		return nil
	}

	// Started only past the dry-run exit: a dry run inspects nothing about
	// the host, and leaving docker probes running after the command returns
	// makes its "no side effects" promise depend on timing.
	preCh := make(chan preflight, 1)
	go func() { preCh <- in.gatherPreflight(ctx) }()

	manifest, err := state.Load(in.root.Dir)
	if err != nil {
		return err
	}
	hadManifest := manifest != nil
	if manifest == nil {
		manifest = &state.Manifest{}
	}
	in.resolveProject(manifest)

	if in.fancy() {
		in.wiz = ui.StartWizard(in.deps.IOS.Out, "Onyx Installer", in.deps.CLIVersion, in.cancel)
		defer in.wiz.Abort()
	}

	// ---- Questions: every decision is made up front ----
	chosenTag := pinnedTag // the tag this run deploys; "" until answered
	var updateTag string   // rerun: non-empty means update to this tag
	pre, preSeen := preflight{}, false
	if rerun {
		// The running-services guard needs docker handles, so resolve the
		// environment before asking anything.
		pre, preSeen = <-preCh, true
		if err := in.resolveDockerProblems(ctx, pre); err != nil {
			return err
		}
		// Read the published port off the running deployment: installs
		// predating HOST_PORT recording have it nowhere else.
		in.observedPort = in.runningHostPort(ctx)
		running, err := in.guardRunningServices(ctx)
		if err != nil {
			return err
		}
		// The mode never changes implicitly on a rerun: the recorded mode
		// (or the overlays on disk) wins unless --lite/--include-craft say
		// otherwise. (install.sh re-asked every run, so a --no-prompt rerun
		// silently flipped standard installs to lite.)
		in.prod = in.opts.Prod || manifest.Mode == state.ModeProd ||
			in.overlayOnDisk(filepath.Base(deployfiles.ProdCompose.DestRel))
		if in.prod && in.opts.Lite {
			return exitcodes.New(exitcodes.BadRequest,
				"this is a prod deployment — --lite cannot be applied to it")
		}
		if in.prod && in.opts.Dev {
			return exitcodes.New(exitcodes.BadRequest,
				"this is a prod deployment — --dev cannot be applied to it")
		}
		in.wasLite = manifest.Mode == state.ModeLite ||
			in.overlayOnDisk(filepath.Base(deployfiles.LiteOverlay.DestRel))
		in.lite = !in.prod && (in.opts.Lite || (!in.opts.IncludeCraft && in.wasLite))
		in.craft = in.opts.IncludeCraft || manifest.IncludeCraft ||
			in.overlayOnDisk(filepath.Base(deployfiles.CraftOverlay.DestRel))
		in.dev = !in.prod && (in.opts.Dev || manifest.Dev ||
			in.overlayOnDisk(filepath.Base(deployfiles.DevOverlay.DestRel)))

		if pinnedTag != "" {
			// --tag already answers the question below.
			updateTag = pinnedTag
		} else if !in.prompt.AssumeDefaults {
			// This is also where a live deployment is signed off on: the
			// choices restart it either way, so a separate "you know this
			// restarts things" confirmation would only ask it twice.
			title, restartHint, cancelHint :=
				"This deployment already exists. What would you like to do?",
				"keep the current configuration",
				"leave the deployment as it is"
			if running {
				title, cancelHint = "Onyx is already running here. What would you like to do?",
					"leave everything running"
			}
			choice, err := in.selectOne(title,
				[]ui.Option{
					{Label: "Restart", Hint: restartHint},
					{Label: "Upgrade", Hint: "move to a newer Onyx version"},
					{Label: "Cancel", Hint: cancelHint},
				}, 0)
			if err != nil {
				return err
			}
			switch choice {
			case 1:
				updateTag, err = in.askVersion(ctx, "Version to deploy", getLatestTag())
				if err != nil {
					return err
				}
			case 2:
				if running {
					return exitcodes.New(exitcodes.General,
						"cancelled — services left running (stop them with `onyx-cli deploy stop`)")
				}
				return exitcodes.New(exitcodes.General, "cancelled")
			}
			if in.wiz != nil {
				if updateTag != "" {
					in.wiz.Answer("Action", "Upgrade")
					in.wiz.Answer("Version", updateTag)
				} else {
					in.wiz.Answer("Action", "Restart")
				}
			}
		}
		if running {
			// Said once, whichever way the decision was reached: the run is
			// about to sit on `pull` for a while, and this is what stops that
			// looking like downtime.
			in.infof("Onyx keeps serving while the images download; each service is replaced once, at the end")
		}
	} else {
		if err := in.askModeQuestion(); err != nil {
			return err
		}
		if chosenTag == "" {
			tag, err := in.askVersion(ctx, "Version to deploy", getLatestTag())
			if err != nil {
				return err
			}
			chosenTag = tag
		}
		if in.wiz != nil {
			in.wiz.Answer("Version", chosenTag)
		}
	}

	// ---- Join the checks; only problems surface ----
	if !preSeen {
		pre = <-preCh
		if err := in.resolveDockerProblems(ctx, pre); err != nil {
			return err
		}
	}
	if err := in.resourceWarnings(pre); err != nil {
		return err
	}
	if err := in.checkComposeVersion(ctx); err != nil {
		return err
	}

	// ---- Phase 1: prepare configuration ----
	in.phase("Preparing configuration")
	if in.root.Source == paths.SourceLegacyCwd {
		in.infof("Managing existing install at %s (created by install.sh)", in.root.Dir)
	}
	for _, alt := range in.root.Ambiguous {
		in.warnf("Another Onyx install exists at %s — pass --dir to target it instead", alt)
	}
	if !hadManifest && paths.IsInstall(in.root.Dir) {
		in.infof("No %s found — adopting this install; files not written by the CLI are treated as potentially customized", state.FileName)
	}
	for _, dir := range []string{
		filepath.Join(in.root.Dir, "deployment"),
		filepath.Join(in.root.Dir, "data", "nginx", "local"),
	} {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return fmt.Errorf("failed to create %s: %w", dir, err)
		}
	}
	gitkeep := filepath.Join(in.root.Dir, "data", "nginx", "local", ".gitkeep")
	if err := os.WriteFile(gitkeep, nil, 0644); err != nil {
		return fmt.Errorf("failed to create %s: %w", gitkeep, err)
	}

	initialTag := chosenTag
	if initialTag == "" {
		if updateTag != "" {
			initialTag = updateTag
		} else {
			initialTag = getLatestTag()
		}
	}
	initialRef := ""
	if !in.localFiles() {
		initialRef = release.ConfigRef(initialTag)
	}
	fetcher := &fileFetcher{in: in}
	if err := in.materializeFiles(ctx, initialRef, managedFiles(in.prod, in.lite, in.craft, in.dev), manifest, fetcher); err != nil {
		return err
	}
	if !in.lite {
		if err := in.removeOverlayIfPresent(deployfiles.LiteOverlay, manifest, "switching to standard mode"); err != nil {
			return err
		}
	}
	if !in.craft {
		if err := in.removeOverlayIfPresent(deployfiles.CraftOverlay, manifest, "Craft disabled this run"); err != nil {
			return err
		}
	}
	if !in.dev {
		if err := in.removeOverlayIfPresent(deployfiles.DevOverlay, manifest, "dev ports not requested this run"); err != nil {
			return err
		}
	}
	if in.dev {
		in.warnf("Dev overlay: Postgres, Redis, OpenSearch, MinIO, the model server and the API are published on this host, not just nginx. Only run it on a machine you trust the network of.")
	}
	in.noteComposeOverride()

	// Captured for rollback: a failed pull must not leave .env pointing at a
	// version that never ran (nil means there was no .env before this run).
	prevEnv, prevErr := os.ReadFile(envPath)
	if prevErr != nil {
		prevEnv = nil
	}

	var effectiveTag string
	var hostPort int
	if rerun {
		effectiveTag, hostPort, err = in.reconfigureExistingEnv(envPath, updateTag)
	} else {
		effectiveTag, hostPort, err = in.createFreshEnv(envPath, initialTag)
	}
	if err != nil {
		return err
	}

	// Pinned tags want config files from their own ref so compose matches
	// the images; re-materialize when the effective tag needs another ref.
	configRef := release.ConfigRef(effectiveTag)
	if !in.localFiles() && configRef != initialRef {
		in.infof("Fetching config files matching %s...", configRef)
		if err := in.materializeFiles(ctx, configRef, managedFiles(in.prod, in.lite, in.craft, in.dev), manifest, fetcher); err != nil {
			// .env already names this version and nothing has been deployed
			// yet, so it is put back for the same reason a failed pull does:
			// a version that never ran must not be left recorded as the
			// deployment's current one.
			in.rollbackEnv(envPath, prevEnv)
			return err
		}
	}

	if in.craft {
		in.ensureCraftResources(ctx)
	}

	in.successf("Configuration ready at %s (version %s)", in.root.Dir, effectiveTag)

	// Persist the manifest's file records now: if the pull fails, the next
	// run must still know the freshly materialized files were CLI-written,
	// not hand-edited. InstalledTag advances only after a successful start.
	if err := manifest.Save(in.root.Dir); err != nil {
		in.rollbackEnv(envPath, prevEnv)
		return err
	}

	// ---- Phases 2 + 3: pull and start ----
	if err := in.pullImages(ctx, effectiveTag, hostPort); err != nil {
		in.rollbackEnv(envPath, prevEnv)
		return err
	}
	if err := in.startServices(ctx, effectiveTag, Var(string(prevEnv), "IMAGE_TAG"), hostPort); err != nil {
		return err
	}

	now := time.Now().UTC()
	manifest.InstalledTag = effectiveTag
	manifest.CLIVersion = in.deps.CLIVersion
	manifest.Mode = state.ModeStandard
	switch {
	case in.lite:
		manifest.Mode = state.ModeLite
	case in.prod:
		manifest.Mode = state.ModeProd
	}
	in.recordProject(manifest)
	manifest.IncludeCraft = in.craft
	manifest.Dev = in.dev
	if !hadManifest || manifest.InstalledAt.IsZero() {
		manifest.InstalledAt = now
	}
	manifest.UpdatedAt = now
	if err := manifest.Save(in.root.Dir); err != nil {
		// The deployment is already up on this version: say what did happen,
		// or the error reads as an install that never took place.
		return fmt.Errorf("deployed %s, but recording it in %s failed: %w", effectiveTag, state.FileName, err)
	}

	in.printSuccess(ctx, hostPort)
	return nil
}

// validateTag normalizes a requested version and, when it can, confirms it
// exists BEFORE anything is written, so a typo fails here instead of
// surfacing minutes later as a pull error with the bad version already in
// .env. Only release versions are looked up: floating and hand-built image
// tags are pullable without a matching git ref. Verification is best-effort
// by design — an unreachable (or lying) GitHub must never be able to block
// an install that would otherwise work.
func (in *installer) validateTag(ctx context.Context, tag string) (string, error) {
	tag = strings.TrimSpace(tag)
	if tag == "" {
		return "", exitcodes.New(exitcodes.BadRequest, "no version given")
	}
	normalized, checkable := release.NormalizeVersionTag(tag)
	if normalized != tag {
		in.infof("Using %s (Onyx versions are v-prefixed)", normalized)
	}
	// A dry run writes nothing and pulls nothing, so it stays offline.
	if !checkable || in.localFiles() || in.opts.DryRun {
		return normalized, nil
	}

	exists, err := in.deps.Release.RefExists(ctx, normalized)
	if err != nil {
		in.warnf("Could not verify that version %s exists (%v) — continuing", normalized, err)
		return normalized, nil
	}
	if exists {
		return normalized, nil
	}
	// A 404 is only worth acting on if the same endpoint answers for a ref
	// that certainly exists: proxies and captive portals 404 everything, and
	// rejecting a real version would leave no way to install at all.
	if ok, cerr := in.deps.Release.RefExists(ctx, "main"); cerr != nil || !ok {
		in.warnf("Could not reach GitHub to verify version %s — continuing", normalized)
		return normalized, nil
	}
	return "", exitcodes.Newf(exitcodes.BadRequest,
		"version %s not found — Onyx releases look like v4.4.6 (https://github.com/onyx-dot-app/onyx/releases)", normalized)
}

// appImage is the one image every deployment runs whatever its mode, so the
// tags present for it are the versions this host could deploy right now.
const appImage = "onyxdotapp/onyx-backend"

// errOffline stands in for the release lookup --offline never makes, so the
// one place that turns a failed lookup into an offered version handles both.
var errOffline = errors.New("offline")

// latestAppTag is the release lookup, skipped outright when --offline says
// the network is not there to be asked.
func (in *installer) latestAppTag(ctx context.Context) (string, error) {
	if in.opts.Offline {
		return "", errOffline
	}
	return in.deps.Release.LatestAppTag(ctx)
}

// unreachableTagFallback picks the version to offer when the latest release
// could not be looked up. A host that already has released images can still
// install from them, and offering one is what makes that possible: edge is a
// floating tag, so choosing it commits the run to another trip to the
// registry — the one thing an absent network guarantees will fail.
func (in *installer) unreachableTagFallback(ctx context.Context) string {
	why := "Could not reach GitHub"
	if in.opts.Offline {
		why = "Offline"
	}
	if local := in.localAppTag(ctx); local != "" {
		in.warnf("%s — offering %s, whose images are already on this host", why, local)
		return local
	}
	if in.opts.Offline {
		// edge may well be here too; it just isn't a version, so it can't be
		// compared with anything or verified as the one that was meant.
		in.warnf("%s — no released Onyx images on this host, offering edge", why)
	} else {
		in.warnf("Could not determine latest Onyx release — falling back to main / edge")
	}
	return "edge"
}

// localAppTag returns the newest released version already pulled on this
// host, or "" when there is none. Only released versions count: a floating
// tag on disk is a copy of whatever main was that day, and deploying it pulls
// again regardless.
func (in *installer) localAppTag(ctx context.Context) string {
	if !dockercmd.Installed() {
		return ""
	}
	in.docker.RefreshSudo(ctx)
	res, err := in.deps.Runner.Run(ctx, in.docker.Command(nil, "images", "--format", "{{.Tag}}", appImage))
	if err != nil {
		return ""
	}
	best, bestVer := "", version.Semver{}
	for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
		tag := strings.TrimSpace(line)
		if !release.IsImmutableTag(tag) {
			continue
		}
		ver, ok := version.Parse(tag)
		if !ok {
			continue
		}
		if best == "" || bestVer.LessThan(ver) {
			best, bestVer = tag, ver
		}
	}
	return best
}

// askVersion asks for a deployment version and validates the answer;
// interactive runs re-ask, seeded with the rejected text so a typo can be
// corrected rather than retyped.
func (in *installer) askVersion(ctx context.Context, title, def string) (string, error) {
	for {
		tag, err := in.askString(title, def)
		if err != nil {
			return "", err
		}
		resolved, verr := in.validateTag(ctx, tag)
		if verr == nil {
			return resolved, nil
		}
		if in.prompt.AssumeDefaults {
			return "", verr
		}
		in.errorf("%v", verr)
		def = tag
	}
}

// askModeQuestion is the deployment-mode select. Lite stays the default for
// new installs, matching install.sh's interactive and --no-prompt behavior.
// Craft is deliberately not offered here: it is reachable with
// --include-craft, and installs it the same way, but it binds the docker
// socket and is not yet something to put in front of someone who has not
// gone looking for it.
func (in *installer) askModeQuestion() error {
	if in.opts.Lite {
		in.infof("Deployment mode: Lite (set via --lite flag)")
		return nil
	}
	if in.opts.IncludeCraft {
		return nil // craft implies standard; the conflict was rejected earlier
	}
	choice, err := in.selectOne("Deployment mode",
		[]ui.Option{
			{Label: "Lite", Hint: "chat, tools, uploads, projects — no vector search (recommended)"},
			{Label: "Standard", Hint: "full search, connectors, and RAG"},
		}, 0)
	if err != nil {
		return err
	}
	in.lite = choice == 0
	if in.wiz != nil {
		in.wiz.Answer("Mode", []string{"Lite", "Standard"}[choice])
	}
	return nil
}

// gatherPreflight collects environment facts without side effects or output.
func (in *installer) gatherPreflight(ctx context.Context) preflight {
	p := preflight{diskGB: resources.DiskAvailableGB(".")}
	if !dockercmd.Installed() {
		return p
	}
	p.dockerVersion = in.docker.Version(ctx)
	if c := dockercmd.DetectCompose(ctx, in.docker); c != nil {
		p.composeVersion = c.Version(ctx)
		p.composeType = c.TypeName()
	}
	dockerInfo := ""
	if res, err := in.deps.Runner.Run(ctx, dockercmd.Command{Name: "docker", Args: []string{"system", "info"}}); err == nil {
		dockerInfo = res.Stdout
	}
	p.memoryMB = resources.MemoryMB(dockerInfo)
	p.rootless = strings.Contains(strings.ToLower(dockerInfo), "rootless")
	return p
}

// resolveDockerProblems provisions or errors for anything missing, then
// prints one compact summary line. Mirrors install.sh's behaviors: Docker
// Engine and compose plugin auto-install on Linux/WSL, Docker Desktop
// start-and-wait on macOS, instructions elsewhere.
func (in *installer) resolveDockerProblems(ctx context.Context, pre preflight) error {
	linuxLike := runtime.GOOS == "linux" || dockercmd.IsWSL()

	if !dockercmd.Installed() {
		switch {
		case linuxLike:
			in.infof("Docker is required but not installed.")
			ok, err := in.confirmYN("Install Docker Engine?", true)
			if err != nil {
				return err
			}
			if !ok {
				return exitcodes.New(exitcodes.General, "Docker is required to run Onyx")
			}
			if err := in.suspend(func() error {
				return dockercmd.InstallDockerLinux(ctx, in.deps.Runner, in.deps.IOS.Out)
			}); err != nil {
				return exitcodes.Newf(exitcodes.General, "Docker installation failed: %v\n  Visit: https://docs.docker.com/get-docker/", err)
			}
			if !dockercmd.Installed() {
				return exitcodes.New(exitcodes.General, "Docker installation failed.\n  Visit: https://docs.docker.com/get-docker/")
			}
			in.successf("Docker installed successfully")
		case runtime.GOOS == "windows":
			in.plainf("%s", dockercmd.DockerDesktopInstructionsWindows)
			return exitcodes.New(exitcodes.General, "Docker Desktop is required to run Onyx")
		default:
			return exitcodes.New(exitcodes.General,
				"Docker is not installed. Please install Docker Desktop first.\n  Visit: https://docs.docker.com/get-docker/")
		}
	}

	in.compose = dockercmd.DetectCompose(ctx, in.docker)
	if in.compose != nil {
		in.compose.Project = in.projectName()
	}
	if in.compose == nil && linuxLike {
		in.infof("Docker Compose is required but not installed.")
		ok, err := in.confirmYN("Install the Docker Compose plugin?", true)
		if err != nil {
			return err
		}
		if !ok {
			return exitcodes.New(exitcodes.General, "Docker Compose is required to run Onyx")
		}
		if err := in.suspend(func() error {
			return dockercmd.InstallComposePluginLinux(ctx, in.deps.Runner, in.deps.IOS.Out)
		}); err != nil {
			return exitcodes.Newf(exitcodes.General, "Failed to install the Docker Compose plugin: %v\n  Visit: https://docs.docker.com/compose/install/", err)
		}
		in.compose = dockercmd.DetectCompose(ctx, in.docker)
		if in.compose == nil {
			return exitcodes.New(exitcodes.General, "Docker Compose plugin installed but not detected.\n  Visit: https://docs.docker.com/compose/install/")
		}
		in.compose.Project = in.projectName()
		in.successf("Docker Compose plugin installed")
	}
	if in.compose == nil {
		return exitcodes.New(exitcodes.General,
			"Docker Compose is not installed. Please install Docker Compose first.\n  Visit: https://docs.docker.com/compose/install/")
	}

	in.docker.RefreshSudo(ctx)
	if in.docker.UsingSudo() {
		if err := in.suspend(func() error {
			return dockercmd.EnsureDockerGroup(ctx, in.deps.Runner, in.deps.IOS.Out)
		}); err != nil {
			in.warnf("Could not add you to the docker group: %v", err)
		}
		in.infof("Using sudo for docker commands in this run.")
	}

	if !in.docker.DaemonRunning(ctx) {
		if runtime.GOOS == "darwin" {
			in.infof("Docker daemon is not running.")
			if err := in.runTask("Starting Docker Desktop", func(progress io.Writer) error {
				return dockercmd.StartDockerDesktopDarwin(ctx, in.docker, progress, dockerDesktopWait)
			}); err != nil {
				return exitcodes.Newf(exitcodes.General, "%v", err)
			}
		} else {
			return exitcodes.New(exitcodes.General, "Docker daemon is not running. Please start Docker.")
		}
	}

	summary := []string{"Docker " + orDetect(pre.dockerVersion, in.docker.Version(ctx))}
	if pre.composeVersion != "" {
		summary = append(summary, fmt.Sprintf("Compose %s (%s)", pre.composeVersion, pre.composeType))
	} else {
		summary = append(summary, fmt.Sprintf("Compose %s (%s)", in.compose.Version(ctx), in.compose.TypeName()))
	}
	summary = append(summary, "daemon running")
	if pre.rootless {
		in.rootless = true
		summary = append(summary, "rootless")
	}
	if pre.memoryMB > 0 {
		summary = append(summary, resources.FormatMemory(pre.memoryMB)+" RAM")
	}
	if pre.diskGB >= 0 {
		summary = append(summary, fmt.Sprintf("%dGB free", pre.diskGB))
	}
	in.successf("%s", strings.Join(summary, " · "))
	return nil
}

func orDetect(v, fallback string) string {
	if v != "" {
		return v
	}
	return fallback
}

// resourceWarnings surfaces low-resource conditions only (healthy machines
// see nothing) and asks whether to continue, like install.sh's warning path.
func (in *installer) resourceWarnings(pre preflight) error {
	ramWant, diskWant := expectedRAMGB, expectedDiskGB
	mode := "standard"
	if in.lite {
		ramWant, diskWant = expectedRAMGBLite, expectedDiskGBLite
		mode = "lite"
	}
	warning := false
	if pre.memoryMB > 0 && pre.memoryMB < ramWant*1024 {
		in.warnf("Less than %dGB RAM available (found: %s)", ramWant, resources.FormatMemory(pre.memoryMB))
		warning = true
	}
	if pre.diskGB >= 0 && pre.diskGB < diskWant {
		in.warnf("Less than %dGB disk space available (found: %dGB)", diskWant, pre.diskGB)
		warning = true
	}
	if in.rootless && !in.lite {
		in.warnf("Rootless Docker: the standard deployment's OpenSearch index requests unlimited memlock, which a rootless daemon usually can't grant.")
		in.infof("Either raise the daemon's limits (systemctl --user edit docker: LimitMEMLOCK=infinity, LimitNOFILE=1048576, then systemctl --user restart docker) or use Lite mode, which has no OpenSearch.")
	}
	if !warning {
		return nil
	}
	in.warnf("Onyx recommends at least %dGB RAM and %dGB disk space in %s mode.", ramWant, diskWant, mode)
	cont, err := in.confirmYN("Continue anyway?", true)
	if err != nil {
		return err
	}
	if !cont {
		return exitcodes.New(exitcodes.General, "Installation cancelled. Please allocate more resources and try again.")
	}
	return nil
}

func (in *installer) checkComposeVersion(ctx context.Context) error {
	if in.compose == nil {
		return nil
	}
	composeVersion := in.compose.Version(ctx)
	if composeVersion == "dev" {
		return nil
	}
	have, ok := version.Parse(composeVersion)
	minimum, _ := version.Parse(minComposeVersion)
	if !ok || !have.LessThan(minimum) {
		return nil
	}
	in.warnf("Docker Compose %s is older than %s; docker-compose.yml uses the newer env_file format.", composeVersion, minComposeVersion)
	in.infof("Upgrade Docker Compose: https://docs.docker.com/compose/install/")
	cont, err := in.confirmYN("Continue anyway?", true)
	if err != nil {
		return err
	}
	if !cont {
		return exitcodes.New(exitcodes.General, "Installation cancelled. Please upgrade Docker Compose and re-run.")
	}
	return nil
}

// createFreshEnv writes deployment/.env from env.template with the chosen
// tag, generated secrets, port, and mode adjustments.
func (in *installer) createFreshEnv(envPath, tag string) (string, int, error) {
	template, err := os.ReadFile(filepath.Join(in.root.Dir, "deployment", "env.template"))
	if err != nil {
		return "", 0, fmt.Errorf("failed to read env.template: %w", err)
	}
	env := string(template)
	env = SetVar(env, "IMAGE_TAG", tag)

	// Recorded in .env so reruns and upgrades reuse the same port instead of
	// re-scanning (which would collide with the deployment's own binding).
	hostPort := resources.FindAvailablePort(3000)
	if hostPort != 3000 {
		in.infof("Port 3000 is in use — using %d", hostPort)
	}
	env = SetVar(env, "HOST_PORT", strconv.Itoa(hostPort))

	if in.lite {
		// MinIO never starts in lite mode and the overlay forces the
		// postgres file store at runtime; align .env so it isn't misleading.
		env = SetVar(env, "COMPOSE_PROFILES", withoutProfile(Var(env, "COMPOSE_PROFILES"), s3FilestoreProfile))
		env = SetVar(env, "FILE_STORE_BACKEND", "postgres")
	}

	env = SetVar(env, "USER_AUTH_SECRET", `"`+randomHex(32)+`"`)
	minioAccessKey, minioSecretKey := randomHex(16), randomHex(32)
	env = SetVar(env, "MINIO_ROOT_USER", minioAccessKey)
	env = SetVar(env, "MINIO_ROOT_PASSWORD", minioSecretKey)
	env = SetVar(env, "S3_AWS_ACCESS_KEY_ID", minioAccessKey)
	env = SetVar(env, "S3_AWS_SECRET_ACCESS_KEY", minioSecretKey)

	if in.craft {
		env = SetVarUncomment(env, "ENABLE_CRAFT", "true")
		backend := sandboxBackendForTag(tag)
		env = SetVarUncomment(env, "SANDBOX_BACKEND", backend)
		in.successf("Onyx Craft enabled (ENABLE_CRAFT=true, SANDBOX_BACKEND=%s)", backend)
		if backend == "docker" {
			in.plainf("%s", craftSecurityWarning)
		} else {
			in.infof("Image tag %s predates the docker sandbox backend (v4.0.6+); using SANDBOX_BACKEND=%s.", tag, backend)
		}
	}

	if err := os.WriteFile(envPath, []byte(env), 0600); err != nil {
		return "", 0, fmt.Errorf("failed to write .env: %w", err)
	}
	in.successf(".env created (auth secret and MinIO credentials generated) — customize it any time")
	return tag, hostPort, nil
}

// reconfigureExistingEnv applies the rerun decision: restart keeps .env
// untouched except craft/lite alignment; a non-empty updateTag rewrites
// IMAGE_TAG (and nothing else).
func (in *installer) reconfigureExistingEnv(envPath, updateTag string) (string, int, error) {
	existing, err := os.ReadFile(envPath)
	if err != nil {
		return "", 0, fmt.Errorf("failed to read %s: %w", envPath, err)
	}
	env := string(existing)

	// Keep the port the deployment already uses. Installs that predate
	// HOST_PORT recording fall back to the port they were observed
	// publishing, and only a deployment that was never up gets a fresh scan
	// (services are stopped on this path, so the scan can't collide with our
	// own binding — but it would silently move a running deployment).
	// Prod ignores HOST_PORT entirely: docker-compose.prod.yml publishes
	// 80/443 outright.
	hostPort := 0
	if !in.prod {
		var perr error
		hostPort, perr = strconv.Atoi(Var(env, "HOST_PORT"))
		if perr != nil {
			switch {
			case in.observedPort != 0:
				hostPort = in.observedPort
				in.infof("Recording the port this deployment already uses (%d) in .env", hostPort)
			default:
				hostPort = resources.FindAvailablePort(3000)
				if hostPort != 3000 {
					in.infof("Port 3000 is in use — using %d", hostPort)
				}
			}
			env = SetVar(env, "HOST_PORT", strconv.Itoa(hostPort))
		}
	}

	if updateTag != "" && updateTag != Var(env, "IMAGE_TAG") {
		env = SetVar(env, "IMAGE_TAG", updateTag)
		in.successf("Updated IMAGE_TAG to %s (all other settings preserved)", updateTag)
	} else {
		in.infof("Restarting with the current configuration")
	}

	effectiveTag := Var(env, "IMAGE_TAG")
	if effectiveTag == "" {
		effectiveTag = "edge"
	}

	// Honor --include-craft on existing installs regardless of branch,
	// aligning SANDBOX_BACKEND with the effective tag.
	if in.craft {
		env = SetVarUncomment(env, "ENABLE_CRAFT", "true")
		backend := sandboxBackendForTag(effectiveTag)
		env = SetVarUncomment(env, "SANDBOX_BACKEND", backend)
		in.successf("Onyx Craft enabled (ENABLE_CRAFT=true, SANDBOX_BACKEND=%s, image tag: %s)", backend, effectiveTag)
	}

	// Lite mode on an existing .env: the template ships with s3-filestore
	// enabled; drop that entry so MinIO doesn't start. Only that entry — any
	// other profile in the list was turned on by the user, and clearing the
	// whole value would switch their services off with no way to name them
	// again on the way back.
	if in.lite && hasProfile(Var(env, "COMPOSE_PROFILES"), s3FilestoreProfile) {
		env = SetVar(env, "COMPOSE_PROFILES", withoutProfile(Var(env, "COMPOSE_PROFILES"), s3FilestoreProfile))
		in.successf("Dropped %s from COMPOSE_PROFILES for lite mode", s3FilestoreProfile)
	}
	// Leaving lite behind: undo those same adjustments, or the "standard"
	// deployment keeps lite's storage behaviour with MinIO never starting.
	// The rest of the profile list, and a file store the user has since
	// pointed somewhere else, are left as they are.
	if !in.lite && in.wasLite {
		env = SetVar(env, "COMPOSE_PROFILES", withProfile(Var(env, "COMPOSE_PROFILES"), s3FilestoreProfile))
		if Var(env, "FILE_STORE_BACKEND") == "postgres" {
			env = SetVar(env, "FILE_STORE_BACKEND", "s3")
			in.warnf("Files stored while in lite mode live in Postgres; standard mode reads the MinIO store, so they won't be listed until you switch back.")
		}
		in.successf("Restored the standard file store (COMPOSE_PROFILES=%s, FILE_STORE_BACKEND=%s)",
			Var(env, "COMPOSE_PROFILES"), Var(env, "FILE_STORE_BACKEND"))
	}

	if err := os.WriteFile(envPath, []byte(env), 0600); err != nil {
		return "", 0, fmt.Errorf("failed to write .env: %w", err)
	}
	return effectiveTag, hostPort, nil
}

// guardRunningServices reports whether the deployment's services are up, and
// settles what that means for a scripted run: reconfiguring a live deployment
// needs --force, and the refusal carries the remedy (install.sh printed
// "./install.sh --shutdown", which doesn't exist after curl|bash). Interactive
// runs are asked instead, by the rerun question — that is where Cancel lives.
//
// Nothing is stopped either way: running services are handed to `up` as
// --force-recreate, so the current version keeps serving while the images
// download and each container is replaced only once its replacement is ready.
func (in *installer) guardRunningServices(ctx context.Context) (bool, error) {
	files := in.composeFileNames(true)
	cmd := in.compose.Command(in.deploymentDir(), stopFallbackEnv(), files, "ps", "-q")
	res, err := in.deps.Runner.Run(ctx, cmd)
	if err != nil || strings.TrimSpace(res.Stdout) == "" {
		return false, nil
	}
	if in.prompt.AssumeDefaults && !in.opts.Force {
		return true, exitcodes.New(exitcodes.General,
			"Onyx services are running — pass --force to recreate them with the new configuration, or stop them first with `onyx-cli deploy stop`")
	}
	in.forceRecreate = true
	return true, nil
}

func (in *installer) ensureCraftResources(ctx context.Context) {
	network := sandboxNetworkName()
	if created, err := in.docker.EnsureNetwork(ctx, network); err != nil {
		in.warnf("Could not create sandbox network %s — create it manually:", network)
		in.cmdf("docker network create %s", network)
	} else if created {
		in.successf("Created sandbox bridge network: %s", network)
	}

	if created, err := in.docker.EnsureVolume(ctx, sandboxProxyCAVolume); err != nil {
		in.warnf("Could not create sandbox proxy CA volume %s — create it manually:", sandboxProxyCAVolume)
		in.cmdf("docker volume create %s", sandboxProxyCAVolume)
	} else if created {
		in.successf("Created sandbox proxy CA volume: %s", sandboxProxyCAVolume)
	}
}

func (in *installer) composeRunEnv(tag string, hostPort int) map[string]string {
	env := map[string]string{"IMAGE_TAG": tag}
	// Prod has no HOST_PORT: docker-compose.prod.yml publishes 80/443
	// outright, so passing one would only suggest it does something.
	if !in.prod {
		env["HOST_PORT"] = fmt.Sprintf("%d", hostPort)
	}
	return env
}

func (in *installer) pullImages(ctx context.Context, tag string, hostPort int) error {
	if in.opts.Offline {
		return in.checkLocalImages(ctx, tag, hostPort)
	}
	phase := composePhase{
		stage: ui.StagePull,
		title: "Pulling images",
		dir:   in.deploymentDir(),
		env:   in.composeRunEnv(tag, hostPort),
		files: in.composeFileNames(false),
		args:  []string{"pull"},
	}
	if release.IsImmutableTag(tag) && in.composeAtLeast(ctx, minPullPolicyVersion) {
		// A released tag names an image that never changes, so a copy already
		// on the host is the copy this deployment wants. Without this compose
		// asks the registry about every service on every run, which is most of
		// the wait on a re-run that has nothing to fetch.
		phase.args = append(phase.args, "--policy", "missing")
	}
	mode := in.progressMode(ctx)
	switch {
	case mode != "":
		// The pull drives the wizard's own checklist, so the full-screen view
		// survives the phase instead of being released to compose's renderer.
		phase.args = append([]string{"--progress", mode}, phase.args...)
		phase.onLine = newPullProgress(in.wiz.Services, in.wiz.TaskExtra).line
		defer in.wiz.Services(nil)
	case !in.opts.Verbose:
		phase.args = append(phase.args, "--quiet")
	}
	if err := in.runComposePhase(ctx, phase); err != nil {
		if ctx.Err() != nil {
			return err
		}
		in.infof("Check your internet connection and re-run. If the issue persists: founders@onyx.app")
		return exitcodes.Newf(exitcodes.General, "docker compose pull failed: %v", err)
	}
	return nil
}

// checkLocalImages replaces the pull when --offline forbids one. It asks
// compose what the deployment resolves to and names every image this host
// doesn't have, because `up` would otherwise stop at the first one it misses
// and report it as a registry error rather than a missing copy. Note that not
// every image follows IMAGE_TAG: code-interpreter carries its own version
// line, so it is pinned separately and is the one most often absent.
func (in *installer) checkLocalImages(ctx context.Context, tag string, hostPort int) error {
	in.phase("Checking images")
	cmd := in.compose.Command(in.deploymentDir(), in.composeRunEnv(tag, hostPort),
		in.composeFileNames(false), "config", "--images")
	res, err := in.deps.Runner.Run(ctx, cmd)
	if err != nil {
		// No list to check against. `up --pull never` still refuses to reach a
		// registry, so let it be the one to object.
		return nil
	}
	var missing []string
	for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
		image := strings.TrimSpace(line)
		if image == "" {
			continue
		}
		if _, ierr := in.deps.Runner.Run(ctx, in.docker.Command(nil, "image", "inspect", image)); ierr != nil {
			missing = append(missing, image)
		}
	}
	if len(missing) == 0 {
		in.successf("Every image this deployment needs is already on this host")
		return nil
	}
	for _, image := range missing {
		in.errorf("Not on this host: %s", image)
	}
	return exitcodes.Newf(exitcodes.NotAvailable,
		"%d image(s) missing — load them with `docker load`, or re-run without --offline to fetch them",
		len(missing))
}

// startServices brings the stack up. prevTag is the version .env carried
// before this run ("" on a fresh install), used only to explain what a failed
// start left behind.
func (in *installer) startServices(ctx context.Context, tag, prevTag string, hostPort int) error {
	env := in.composeRunEnv(tag, hostPort)
	files := in.composeFileNames(false)
	dir := in.deploymentDir()

	upArgs := []string{"up", "-d"}
	recreate := true
	switch {
	case in.opts.Offline:
		// Compose consults the registry for any service whose own policy says
		// to, whatever the tag; --pull never is what makes --offline a promise
		// rather than a preference. No image can have moved under a name while
		// the host was offline, so nothing needs recreating for its own sake.
		upArgs = append(upArgs, "--pull", "never")
		recreate = in.forceRecreate
		if recreate {
			upArgs = append(upArgs, "--force-recreate")
		}
	case release.IsFloatingTag(tag):
		// A floating tag names a moving image: the digest changes under the
		// same name, so neither the pull nor the recreate can be skipped.
		upArgs = append(upArgs, "--pull", "always", "--force-recreate")
	case in.forceRecreate:
		// Services were up when the run started and the operator signed off
		// on replacing them; compose would otherwise leave containers whose
		// config it considers unchanged running the old image.
		upArgs = append(upArgs, "--force-recreate")
	default:
		// Compose decides per container, so a container still on the one it
		// started on may be one it means to leave alone.
		recreate = false
	}
	wait := !in.opts.NoWait
	if wait {
		upArgs = append(upArgs, "--wait", "--wait-timeout", fmt.Sprintf("%d", waitTimeoutSeconds))
	}
	phase := composePhase{
		stage: ui.StageStart,
		title: "Starting services",
		dir:   dir,
		env:   env,
		files: files,
		args:  upArgs,
	}
	if wait && in.wiz != nil && !in.opts.Verbose {
		// Watch container states so the wizard shows something while
		// `up --wait` blocks (it is silent for as long as that takes).
		phase.watch = &healthWatch{before: in.runningContainers(ctx), recreate: recreate, project: in.projectName()}
	}
	if mode := in.progressMode(ctx); mode != "" {
		// Compose's own event stream names every transition, which is more than
		// a container list can show. The watch stays on behind it though: a
		// compose that prints no events (a format we can't read, output
		// swallowed by a wrapper) would otherwise leave the longest phase of
		// the run with nothing on screen at all.
		phase.args = append([]string{"--progress", mode}, upArgs...)
		start := newStartProgress(in.wiz.Services, in.wiz.TaskExtra, wait, in.projectName())
		phase.onLine = start.line
		if phase.watch != nil {
			phase.watch.quiet = func() bool { return !start.reporting() }
		}
		defer in.wiz.Services(nil)
	}
	if err := in.runComposePhase(ctx, phase); err != nil {
		if ctx.Err() != nil {
			// Cancelled, not broken. Quitting stops compose, not the containers
			// it had already brought up, which is worth saying before the run
			// reports itself cancelled.
			in.infof("Services that already started are still running:")
			in.cmdf("onyx-cli deploy status%s", in.dirArg())
			in.cmdf("onyx-cli deploy stop%s", in.dirArg())
			return err
		}
		in.infof("Current container status:")
		ps := in.compose.Command(dir, env, files, "ps")
		ps.Stdout, ps.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
		_, _ = in.deps.Runner.Run(ctx, ps)
		in.infof("Check the logs of any unhealthy service:")
		in.cmdf("onyx-cli deploy status%s", in.dirArg())
		in.cmdf("onyx-cli deploy logs%s <service>", in.dirArg())
		in.explainIncompleteStart(tag, prevTag)
		in.infof("If the issue persists, please contact: founders@onyx.app")
		return exitcodes.Newf(exitcodes.General, "docker compose up failed: %v", err)
	}
	return nil
}

// explainIncompleteStart says what a half-finished `up` left behind. Unlike a
// failed pull, .env is deliberately NOT reverted here: containers that did
// come up are running the new images, so putting the old version back would
// deploy older code over data the new one may already have migrated, and on a
// fresh install .env holds the secrets the volumes were just initialized with.
// The manifest still records the previously deployed version, so `deploy
// status` reports the split rather than claiming the move succeeded.
func (in *installer) explainIncompleteStart(tag, prevTag string) {
	switch {
	case prevTag == "":
		in.warnf("Keep %s: it holds the secrets any volumes created just now were initialized with.",
			filepath.Join("deployment", ".env"))
		in.infof("Fix the problem above and re-run %s, or start clean with %s.",
			in.paint.Accent("onyx-cli deploy install"), in.paint.Accent("onyx-cli deploy uninstall"))
	case prevTag != tag:
		in.warnf("Partially deployed: services that started are on %s, the rest are still on %s.", tag, prevTag)
		in.infof("`.env` stays on %s so a re-run finishes the move; to go back, run %s.",
			tag, in.paint.Accent(fmt.Sprintf("onyx-cli deploy upgrade --tag %s", prevTag)))
	}
}

// rollbackEnv restores .env to its pre-run content after a failed pull, so a
// version that never ran isn't left recorded as the deployment's current one.
// Only .env is reverted: the managed config files have already been refreshed
// to the target ref, and re-running completes the move.
func (in *installer) rollbackEnv(envPath string, prev []byte) {
	if prev == nil {
		if err := os.Remove(envPath); err != nil {
			in.warnf("Could not remove the incomplete .env: %v", err)
			return
		}
		in.infof("Removed the incomplete .env — nothing was deployed; re-run to start over")
		return
	}
	if err := os.WriteFile(envPath, prev, 0600); err != nil {
		in.warnf("Could not restore .env: %v", err)
		return
	}
	in.infof("Restored .env to the previously deployed version — re-run to retry")
}

// runningHostPort reports the host port the deployment currently publishes,
// or 0 when nothing is running. It is the only record of the port for
// installs created by install.sh, which never wrote HOST_PORT to .env.
func (in *installer) runningHostPort(ctx context.Context) int {
	if !dockercmd.Installed() {
		return 0
	}
	res, err := in.deps.Runner.Run(ctx, in.psCommand("{{.Ports}}"))
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
		if port, perr := strconv.Atoi(publishedHostPort(line)); perr == nil {
			return port
		}
	}
	return 0
}

// composePhase describes one long compose invocation shown as a single phase.
type composePhase struct {
	stage int
	title string
	dir   string
	env   map[string]string
	files []string
	args  []string
	// watch reads container states off `docker ps` while the command runs;
	// nil for phases with no containers to watch.
	watch *healthWatch
	// onLine receives each output line while the wizard drives the run, for
	// phases whose progress can be read off the command's own output.
	onLine func(string)
}

// runComposePhase runs one long compose command as a visible phase: a rail
// stage with a live task (and per-service checklist) in the wizard, streamed
// output otherwise. On failure only the log tail is shown.
func (in *installer) runComposePhase(ctx context.Context, p composePhase) error {
	cmd := in.compose.Command(p.dir, p.env, p.files, p.args...)

	if in.wiz == nil || in.opts.Verbose {
		in.phase(p.title)
		var seen bytes.Buffer
		cmd.Stdout = io.MultiWriter(in.deps.IOS.Out, &seen)
		cmd.Stderr = io.MultiWriter(in.deps.IOS.ErrOut, &seen)
		_, err := in.deps.Runner.Run(ctx, cmd)
		switch {
		case err == nil:
			in.successf("%s complete", p.title)
		case ctx.Err() == nil:
			in.errorf("%s failed", p.title)
			in.printFailureDiagnosis(seen.String())
		}
		return err
	}

	in.wiz.Stage(p.stage)
	in.wiz.TaskStart(p.title)
	var captured bytes.Buffer
	// One writer for both streams: os/exec then serializes the copies, which
	// is what lets onLine run without a lock.
	var sink io.Writer = &captured
	if p.onLine != nil {
		sink = io.MultiWriter(&captured, &lineWriter{emit: p.onLine})
	}
	cmd.Stdout, cmd.Stderr = sink, sink

	watchCtx, stopWatch := context.WithCancel(ctx)
	watching := make(chan struct{})
	if p.watch == nil {
		close(watching)
	} else {
		go in.pollServiceHealth(watchCtx, in.wiz, *p.watch, watching)
	}
	_, err := in.deps.Runner.Run(ctx, cmd)
	// The watch has to be off the screen before the phase ends: a repaint
	// landing after TaskDone would redraw a finished phase as running, and
	// after a failed one it would race the teardown below.
	stopWatch()
	<-watching
	in.wiz.TaskDone(err == nil)

	if err != nil {
		// Tear the wizard down so the tail prints as plain scrollback.
		in.wiz.Abort()
		in.wiz = nil
		if ctx.Err() != nil {
			// Quitting killed the command mid-sentence. What it had written by
			// then describes nothing that went wrong, so it is not shown.
			return err
		}
		for _, l := range failureTail(captured.String(), failureLogTail) {
			in.plainf("  %s", l)
		}
		in.printFailureDiagnosis(captured.String())
	}
	return err
}

// printFailureDiagnosis translates known failure signatures in compose
// output into targeted remedies instead of leaving raw runtime errors.
func (in *installer) printFailureDiagnosis(output string) {
	lower := strings.ToLower(output)
	if strings.Contains(lower, "setting rlimit") || strings.Contains(lower, "memlock") {
		in.plainf("")
		in.warnf("This looks like a ulimit failure: the OpenSearch index container requests unlimited memlock, which rootless Docker (and some hosts) can't grant.")
		in.infof("Fix one of these ways, then re-run:")
		in.plainf("  • Raise the daemon limits: %s → [Service] LimitMEMLOCK=infinity, LimitNOFILE=1048576 → %s",
			in.paint.Accent("systemctl --user edit docker"), in.paint.Accent("systemctl --user restart docker"))
		in.plainf("    (OpenSearch may also need: %s)", in.paint.Accent("sudo sysctl -w vm.max_map_count=262144"))
		in.plainf("  • Or deploy Lite mode (no OpenSearch): %s", in.paint.Accent("onyx-cli deploy install --lite"))
		return
	}
	if strings.Contains(lower, "address already in use") || strings.Contains(lower, "port is already allocated") {
		in.plainf("")
		in.warnf("A required port is taken by another process. Stop it, or set HOST_PORT before re-running.")
	}
}

// pollServiceHealth feeds the wizard a live per-service checklist while
// `up --wait` blocks (otherwise silent for up to ten minutes). It runs until
// ctx is cancelled and closes done on the way out, so the phase can be sure
// nothing else paints before it reports its own result.
func (in *installer) pollServiceHealth(ctx context.Context, wiz *ui.Wizard, w healthWatch, done chan struct{}) {
	defer close(done)
	tick := time.NewTicker(healthPollInterval)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
		if w.quiet != nil && !w.quiet() {
			continue
		}
		res, err := in.deps.Runner.Run(ctx, in.psCommand("{{.Names}}\t{{.ID}}\t{{.Status}}"))
		if err != nil {
			continue
		}
		rows, ready := watchRows(res.Stdout, w)
		if len(rows) > 0 {
			wiz.Services(rows)
			wiz.TaskExtra(fmt.Sprintf("%d/%d ready", ready, len(rows)))
		}
	}
}

// psCommand lists the deployment's running containers in the given format.
func (in *installer) psCommand(format string) dockercmd.Command {
	return in.docker.Command(nil, "ps",
		"--filter", "label=com.docker.compose.project="+in.projectName(),
		"--format", format)
}

// runningContainers maps each running service to the container serving it, so
// a phase that replaces containers can tell which ones it has got to.
func (in *installer) runningContainers(ctx context.Context) map[string]string {
	if !dockercmd.Installed() {
		return nil
	}
	res, err := in.deps.Runner.Run(ctx, in.psCommand("{{.Names}}\t{{.ID}}"))
	if err != nil {
		return nil
	}
	before := map[string]string{}
	for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
		if name, id, ok := strings.Cut(line, "\t"); ok {
			before[shortContainerName(name, in.projectName())] = id
		}
	}
	return before
}

func (in *installer) printSuccess(ctx context.Context, hostPort int) {
	url := fmt.Sprintf("http://localhost:%d", hostPort)
	if in.prod {
		url = in.prodAccessURL()
	}
	headline := "Onyx is ready"
	if url != "" {
		headline += "  →  " + ui.Accent(url)
	}
	if in.opts.NoWait {
		headline = "Onyx containers started (still initializing — check: " + ui.Accent("onyx-cli deploy status") + ")"
	}
	lines := []string{headline}
	if !in.prod {
		// Prod deployments have their auth configured already; the signup
		// pointer belongs to first-run installs.
		lines = append(lines, "",
			"First signup becomes the admin account: "+url+"/auth/signup")
	}
	if in.lite {
		lines = append(lines, "",
			"Lite mode: no OpenSearch/Redis/model servers or background workers.",
			"Connectors and RAG search are off; chat, tools, uploads, projects work.")
	}
	if in.dev {
		lines = append(lines, "",
			"Dev overlay: the API (8080) and the data services (Postgres, Redis,",
			"OpenSearch, MinIO, model server) are published on this host.")
	}
	lines = append(lines, "")
	lines = append(lines, manageLines()...)

	if in.wiz != nil {
		// The install is over by the time the star question is on screen, so
		// the rail says so rather than leaving a stage mid-flight behind it.
		in.wiz.Stage(ui.StageComplete)
		star := in.askStarQuestion()
		in.wiz.Finish(append([]string{"🎉 " + lines[0]}, lines[1:]...)...)
		in.wiz = nil
		if star {
			in.starRepo(ctx)
		}
		return
	}
	in.plainf("")
	for _, l := range lines {
		in.plainf("%s", l)
	}
	in.plainf("")
	in.infof("For help or issues, contact: founders@onyx.app")
	in.starPrompt(ctx)
}

// prodAccessURL reads the deployment's public URL off .env.nginx, or "" when
// no DOMAIN is recorded there. Prod publishes 80/443 under a real domain, so
// "http://localhost:<port>" would name a URL that serves nothing.
func (in *installer) prodAccessURL() string {
	data, err := os.ReadFile(filepath.Join(in.deploymentDir(), ".env.nginx"))
	if err != nil {
		return ""
	}
	if domain := Var(string(data), "DOMAIN"); domain != "" {
		return "https://" + domain
	}
	return ""
}

// recordProject stores the compose project in the manifest when it differs
// from the default; the default stays implicit so existing manifests don't
// all gain a field that repeats a constant.
func (in *installer) recordProject(manifest *state.Manifest) {
	if in.project != dockercmd.DefaultProjectName {
		manifest.Project = in.project
	} else {
		manifest.Project = ""
	}
}

// manageLines closes a summary card with the verbs that come after the
// install. The installer is typically run once and then forgotten, so the
// commands that keep the deployment going get a spelled-out block rather than
// a single line of "status · stop · upgrade" — the point is that the reader
// recognizes them months later, when something needs doing.
func manageLines() []string {
	cmds := []struct{ cmd, what string }{
		{"onyx-cli deploy status", "health, version, and URL"},
		{"onyx-cli deploy upgrade", "move to a newer version"},
		{"onyx-cli deploy stop", "shut the services down"},
		{"onyx-cli deploy uninstall", "remove it and its data"},
	}
	width := 0
	for _, c := range cmds {
		width = max(width, len(c.cmd))
	}
	lines := []string{"Manage this deployment any time with:"}
	for _, c := range cmds {
		lines = append(lines, "  "+ui.Accent(fmt.Sprintf("%-*s", width, c.cmd))+"   "+c.what)
	}
	return lines
}

// starPrompt ports install.sh's GitHub star prompt: only when interactive
// and the gh CLI is available.
func (in *installer) starPrompt(ctx context.Context) {
	if in.askStarQuestion() {
		in.starRepo(ctx)
	}
}

// askStarQuestion asks while the UI is still live (the wizard closes on
// Finish, so callers ask first and run the API call after).
func (in *installer) askStarQuestion() bool {
	if in.prompt.AssumeDefaults || in.opts.Offline {
		return false
	}
	if _, err := exec.LookPath("gh"); err != nil {
		return false
	}
	ok, err := in.confirmYN("Enjoying Onyx? ⭐ Star the repo on GitHub?", true)
	return err == nil && ok
}

func (in *installer) starRepo(ctx context.Context) {
	cmd := dockercmd.Command{
		Name: "gh",
		Args: []string{"api", "-X", "PUT", "/user/starred/onyx-dot-app/onyx"},
		Env:  map[string]string{"GH_PAGER": ""},
	}
	if _, err := in.deps.Runner.Run(ctx, cmd); err == nil {
		in.successf("Thanks for the star!")
	} else {
		in.infof("Star us at: https://github.com/onyx-dot-app/onyx")
	}
}

// composeFileNames returns the -f list: the managed files for the mode, then
// whichever of deployfiles.OverrideNames the deployment directory has. The
// override always comes last so its edits win the merge, and it ignores
// autoDetect — no flag selects it, only its presence on disk.
func (in *installer) composeFileNames(autoDetect bool) []string {
	files := in.managedComposeFiles(autoDetect)
	if name := in.composeOverrideName(); name != "" {
		files = append(files, name)
	}
	return files
}

// composeOverrideName returns the deployment directory's override filename,
// resolved in deployfiles.OverrideNames precedence order (first match wins,
// the same rule Compose's own auto-discovery uses), or "" when none is
// present.
func (in *installer) composeOverrideName() string {
	for _, name := range deployfiles.OverrideNames {
		if in.overlayOnDisk(name) {
			return name
		}
	}
	return ""
}

// noteComposeOverride says the override is in the -f list. Its presence on
// disk is the only thing that selects it, so a run that stays quiet makes the
// user's customizations look like they came from the managed files.
func (in *installer) noteComposeOverride() {
	name := in.composeOverrideName()
	if name == "" {
		return
	}
	in.infof("Using your %s — it is applied last, and the CLI never overwrites it", name)
}

// managedComposeFiles returns the CLI-managed part of the -f list. Prod
// deployments run the standalone docker-compose.prod.yml on its own; every
// other mode stacks overlays on docker-compose.yml. With autoDetect,
// previously downloaded files are picked up from disk so users don't have to
// repeat --lite/--prod/--include-craft/--dev for lifecycle commands
// (install.sh's build_compose_file_args true).
func (in *installer) managedComposeFiles(autoDetect bool) []string {
	prodName := filepath.Base(deployfiles.ProdCompose.DestRel)
	craftName := filepath.Base(deployfiles.CraftOverlay.DestRel)
	if in.prod || (autoDetect && in.overlayOnDisk(prodName)) {
		files := []string{prodName}
		if in.craft || (autoDetect && in.overlayOnDisk(craftName)) {
			files = append(files, craftName)
		}
		return files
	}
	files := []string{"docker-compose.yml"}
	liteName := filepath.Base(deployfiles.LiteOverlay.DestRel)
	if in.lite || (autoDetect && in.overlayOnDisk(liteName)) {
		files = append(files, liteName)
	}
	if in.craft || (autoDetect && in.overlayOnDisk(craftName)) {
		files = append(files, craftName)
	}
	// Last of the managed files, so the ports and build targets it publishes
	// are the ones that survive the merge — that is the whole point of the
	// overlay.
	devName := filepath.Base(deployfiles.DevOverlay.DestRel)
	if in.dev || (autoDetect && in.overlayOnDisk(devName)) {
		files = append(files, devName)
	}
	return files
}

func (in *installer) overlayOnDisk(name string) bool {
	_, err := os.Stat(filepath.Join(in.deploymentDir(), name))
	return err == nil
}

func (in *installer) deploymentDir() string {
	return filepath.Join(in.root.Dir, "deployment")
}

// hasComposeFile reports whether the deployment dir carries a compose file
// the lifecycle verbs can drive: the base file, or the standalone prod file
// (prod roots managed by the CLI have no docker-compose.yml).
func (in *installer) hasComposeFile() bool {
	return in.overlayOnDisk("docker-compose.yml") ||
		in.overlayOnDisk(filepath.Base(deployfiles.ProdCompose.DestRel))
}

// stopFallbackEnv supplies safe defaults for compose invocations that may run
// before .env is known-good (install.sh uses the same pair for shutdown).
func stopFallbackEnv() map[string]string {
	return map[string]string{"HOST_PORT": "3000", "IMAGE_TAG": "edge"}
}
