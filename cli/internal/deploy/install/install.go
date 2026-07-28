package install

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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
)

// preflight carries the environment facts gathered concurrently while the
// user answers the setup questions. Healthy values stay quiet; only problems
// surface as warnings or provisioning offers.
type preflight struct {
	dockerVersion  string
	composeVersion string
	composeType    string
	memoryMB       int
	diskGB         int
}

// RunInstall implements `deploy install` (and the install-onyx alias): fresh
// installs, and restart/update runs against an existing deployment.
func RunInstall(ctx context.Context, deps Deps, opts Options) error {
	in := newInstaller(deps, opts)
	in.lite = opts.Lite
	in.craft = opts.IncludeCraft
	return in.runInstall(ctx)
}

func (in *installer) runInstall(ctx context.Context) error {
	if in.opts.Lite && in.opts.IncludeCraft {
		return exitcodes.New(exitcodes.BadRequest,
			"--lite and --include-craft cannot be used together: Craft requires services (Vespa, Redis, background workers) that lite mode disables")
	}

	in.root = paths.Resolve(in.opts.Dir)
	envPath := filepath.Join(in.deploymentDir(), ".env")
	_, envErr := os.Stat(envPath)
	rerun := envErr == nil

	// The latest-release lookup and the environment checks run in the
	// background while the user answers the questions below.
	tagCh := make(chan string, 1)
	go func() {
		if in.opts.Local {
			tagCh <- "edge"
			return
		}
		if in.opts.Tag != "" {
			tagCh <- in.opts.Tag
			return
		}
		if tag, err := in.deps.Release.LatestAppTag(ctx); err == nil {
			tagCh <- tag
		} else {
			in.warnf("Could not determine latest Onyx release — falling back to main / edge")
			tagCh <- "edge"
		}
	}()
	preCh := make(chan preflight, 1)
	go func() { preCh <- in.gatherPreflight(ctx) }()

	if in.opts.DryRun {
		in.printPlan(<-tagCh)
		return nil
	}

	manifest, err := state.Load(in.root.Dir)
	if err != nil {
		return err
	}
	hadManifest := manifest != nil
	if manifest == nil {
		manifest = &state.Manifest{}
	}

	if in.fancy() {
		in.wiz = ui.StartWizard(in.deps.CLIVersion)
		defer in.wiz.Abort()
	}

	// ---- Questions: every decision is made up front ----
	var updateTag string // rerun: non-empty means update to this tag
	pre, preSeen := preflight{}, false
	if rerun {
		// The running-services guard needs docker handles, so resolve the
		// environment before asking anything.
		pre, preSeen = <-preCh, true
		if err := in.resolveDockerProblems(ctx, pre); err != nil {
			return err
		}
		if err := in.guardServicesStopped(ctx); err != nil {
			return err
		}
		// The mode never changes implicitly on a rerun: the recorded mode
		// (or the overlays on disk) wins unless --lite/--include-craft say
		// otherwise. (install.sh re-asked every run, so a --no-prompt rerun
		// silently flipped standard installs to lite.)
		in.lite = in.opts.Lite || (!in.opts.IncludeCraft &&
			(manifest.Mode == state.ModeLite || in.overlayOnDisk(filepath.Base(deployfiles.LiteOverlay.DestRel))))
		in.craft = in.opts.IncludeCraft || manifest.IncludeCraft ||
			in.overlayOnDisk(filepath.Base(deployfiles.CraftOverlay.DestRel))

		if in.opts.Tag != "" {
			updateTag = in.opts.Tag
		} else if !in.prompt.AssumeDefaults {
			choice, err := in.selectOne("This deployment already exists. What would you like to do?",
				[]ui.Option{
					{Label: "Restart", Hint: "keep the current configuration"},
					{Label: "Upgrade", Hint: "move to a newer Onyx version"},
				}, 0)
			if err != nil {
				return err
			}
			if choice == 1 {
				updateTag, err = in.askString("Version to deploy", <-tagCh)
				if err != nil {
					return err
				}
			}
			if in.wiz != nil {
				action := "Restart"
				if updateTag != "" {
					action = "Upgrade → " + updateTag
				}
				in.wiz.Answer("Action", action)
			}
		}
	} else {
		if err := in.askModeQuestion(); err != nil {
			return err
		}
		if in.opts.Tag == "" {
			tag, err := in.askString("Version to deploy", <-tagCh)
			if err != nil {
				return err
			}
			in.opts.Tag = tag
		}
		if in.wiz != nil {
			in.wiz.Answer("Version", in.opts.Tag)
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

	initialTag := in.opts.Tag
	if initialTag == "" {
		initialTag = <-tagCh
	}
	initialRef := ""
	if !in.opts.Local {
		initialRef = release.ConfigRef(initialTag)
	}
	fetcher := &fileFetcher{in: in}
	if err := in.materializeFiles(ctx, initialRef, managedFiles(in.lite, in.craft), manifest, fetcher); err != nil {
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

	var effectiveTag string
	if rerun {
		effectiveTag, err = in.reconfigureExistingEnv(envPath, updateTag)
	} else {
		effectiveTag, err = in.createFreshEnv(envPath, initialTag)
	}
	if err != nil {
		return err
	}

	// Pinned tags want config files from their own ref so compose matches
	// the images; re-materialize when the effective tag needs another ref.
	configRef := release.ConfigRef(effectiveTag)
	if !in.opts.Local && configRef != initialRef {
		in.infof("Fetching config files matching %s...", configRef)
		if err := in.materializeFiles(ctx, configRef, managedFiles(in.lite, in.craft), manifest, fetcher); err != nil {
			return err
		}
	}

	if in.craft {
		in.ensureCraftResources(ctx)
	}

	hostPort := resources.FindAvailablePort(3000)
	if hostPort != 3000 {
		in.infof("Port 3000 is in use — using %d", hostPort)
	}
	in.successf("Configuration ready at %s (version %s)", in.root.Dir, effectiveTag)

	// ---- Phases 2 + 3: pull and start ----
	if err := in.pullAndStart(ctx, effectiveTag, hostPort); err != nil {
		return err
	}

	now := time.Now().UTC()
	manifest.InstalledTag = effectiveTag
	manifest.CLIVersion = in.deps.CLIVersion
	manifest.Mode = state.ModeStandard
	if in.lite {
		manifest.Mode = state.ModeLite
	}
	manifest.IncludeCraft = in.craft
	if !hadManifest || manifest.InstalledAt.IsZero() {
		manifest.InstalledAt = now
	}
	manifest.UpdatedAt = now
	if err := manifest.Save(in.root.Dir); err != nil {
		return err
	}

	in.printSuccess(ctx, hostPort)
	return nil
}

// askModeQuestion is the single merged deployment-mode select (mode and
// Craft in one question). Lite stays the default for new installs, matching
// install.sh's interactive and --no-prompt behavior.
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
			{Label: "Standard + Craft", Hint: "adds AI web-app building (binds the docker socket)"},
		}, 0)
	if err != nil {
		return err
	}
	in.lite = choice == 0
	in.craft = choice == 2
	if in.wiz != nil {
		in.wiz.Answer("Mode", []string{"Lite", "Standard", "Std+Craft"}[choice])
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
			in.infof("Docker daemon is not running. Starting Docker Desktop...")
			if err := in.suspend(func() error {
				return dockercmd.StartDockerDesktopDarwin(ctx, in.docker, in.deps.IOS.Out, 120*time.Second)
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
// tag, generated secrets, and mode adjustments.
func (in *installer) createFreshEnv(envPath, tag string) (string, error) {
	template, err := os.ReadFile(filepath.Join(in.root.Dir, "deployment", "env.template"))
	if err != nil {
		return "", fmt.Errorf("failed to read env.template: %w", err)
	}
	env := string(template)
	env = SetVar(env, "IMAGE_TAG", tag)

	if in.lite {
		// MinIO never starts in lite mode and the overlay forces the
		// postgres file store at runtime; align .env so it isn't misleading.
		env = SetVar(env, "COMPOSE_PROFILES", "")
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
		return "", fmt.Errorf("failed to write .env: %w", err)
	}
	in.successf(".env created (auth secret and MinIO credentials generated) — customize it any time")
	return tag, nil
}

// reconfigureExistingEnv applies the rerun decision: restart keeps .env
// untouched except craft/lite alignment; a non-empty updateTag rewrites
// IMAGE_TAG (and nothing else).
func (in *installer) reconfigureExistingEnv(envPath, updateTag string) (string, error) {
	existing, err := os.ReadFile(envPath)
	if err != nil {
		return "", fmt.Errorf("failed to read %s: %w", envPath, err)
	}
	env := string(existing)

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
	// enabled; clear it so MinIO doesn't start.
	if in.lite && strings.Contains(Var(env, "COMPOSE_PROFILES"), "s3-filestore") {
		env = SetVar(env, "COMPOSE_PROFILES", "")
		in.successf("Cleared COMPOSE_PROFILES for lite mode")
	}

	if err := os.WriteFile(envPath, []byte(env), 0600); err != nil {
		return "", fmt.Errorf("failed to write .env: %w", err)
	}
	return effectiveTag, nil
}

// guardServicesStopped handles reconfiguring while containers are up:
// interactive runs offer to stop them right here; non-interactive runs
// refuse with the remedy in the error itself (install.sh printed
// "./install.sh --shutdown", which doesn't exist after curl|bash).
func (in *installer) guardServicesStopped(ctx context.Context) error {
	files := in.composeFileNames(true)
	cmd := in.compose.Command(in.deploymentDir(), stopFallbackEnv(), files, "ps", "-q")
	res, err := in.deps.Runner.Run(ctx, cmd)
	if err != nil || strings.TrimSpace(res.Stdout) == "" {
		return nil
	}

	if in.prompt.AssumeDefaults {
		return exitcodes.New(exitcodes.General,
			"Onyx services are running — stop them first with `onyx-cli deploy stop`, then re-run")
	}

	choice, err := in.selectOne("Onyx is already running. Reconfiguring needs the services stopped.",
		[]ui.Option{
			{Label: "Stop and continue", Hint: "pause the containers (no data loss), then proceed"},
			{Label: "Cancel", Hint: "leave everything running"},
		}, 0)
	if err != nil {
		return err
	}
	if choice != 0 {
		return exitcodes.New(exitcodes.General,
			"cancelled — services left running (stop them with `onyx-cli deploy stop`)")
	}

	in.infof("Stopping Onyx services...")
	stop := in.compose.Command(in.deploymentDir(), stopFallbackEnv(), files, "stop")
	if in.wiz == nil {
		stop.Stdout, stop.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
	}
	if _, err := in.deps.Runner.Run(ctx, stop); err != nil {
		return exitcodes.Newf(exitcodes.General, "failed to stop the running services: %v", err)
	}
	in.successf("Services stopped")
	return nil
}

func (in *installer) ensureCraftResources(ctx context.Context) {
	network := sandboxNetworkName()
	if created, err := in.docker.EnsureNetwork(ctx, network); err != nil {
		in.warnf("Could not create sandbox network %s — create it manually:", network)
		in.plainf("    docker network create %s", network)
	} else if created {
		in.successf("Created sandbox bridge network: %s", network)
	}

	if created, err := in.docker.EnsureVolume(ctx, sandboxProxyCAVolume); err != nil {
		in.warnf("Could not create sandbox proxy CA volume %s — create it manually:", sandboxProxyCAVolume)
		in.plainf("    docker volume create %s", sandboxProxyCAVolume)
	} else if created {
		in.successf("Created sandbox proxy CA volume: %s", sandboxProxyCAVolume)
	}
}

func (in *installer) pullAndStart(ctx context.Context, tag string, hostPort int) error {
	env := map[string]string{
		"HOST_PORT": fmt.Sprintf("%d", hostPort),
		"IMAGE_TAG": tag,
	}
	files := in.composeFileNames(false)
	dir := in.deploymentDir()
	floating := release.IsFloatingTag(tag)

	pullArgs := []string{"pull"}
	if !in.opts.Verbose {
		pullArgs = append(pullArgs, "--quiet")
	}
	if err := in.runComposePhase(ctx, ui.StagePull, "Pulling images", dir, env, files, pullArgs, false); err != nil {
		in.infof("Check your internet connection and re-run. If the issue persists: founders@onyx.app")
		return exitcodes.Newf(exitcodes.General, "docker compose pull failed: %v", err)
	}

	upArgs := []string{"up", "-d"}
	if floating {
		upArgs = append(upArgs, "--pull", "always", "--force-recreate")
	}
	poll := false
	if !in.opts.NoWait {
		upArgs = append(upArgs, "--wait", "--wait-timeout", fmt.Sprintf("%d", waitTimeoutSeconds))
		poll = true
	}
	if err := in.runComposePhase(ctx, ui.StageStart, "Starting services", dir, env, files, upArgs, poll); err != nil {
		in.infof("Current container status:")
		ps := in.compose.Command(dir, env, files, "ps")
		ps.Stdout, ps.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
		_, _ = in.deps.Runner.Run(ctx, ps)
		in.infof("Check the logs of any unhealthy service:")
		in.plainf("  onyx-cli deploy status")
		in.plainf("  (cd %q && docker compose %s logs <service>)", dir, strings.Join(fileArgs(files), " "))
		in.infof("If the issue persists, please contact: founders@onyx.app")
		return exitcodes.Newf(exitcodes.General, "docker compose up failed: %v", err)
	}
	return nil
}

// runComposePhase runs one long compose command as a visible phase: a rail
// stage with a live task (and per-service checklist) in the wizard, streamed
// output otherwise. On failure only the log tail is shown.
func (in *installer) runComposePhase(
	ctx context.Context,
	stage int,
	title, dir string,
	env map[string]string,
	files, args []string,
	poll bool,
) error {
	cmd := in.compose.Command(dir, env, files, args...)

	if in.wiz == nil || in.opts.Verbose {
		in.phase(title)
		cmd.Stdout, cmd.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
		_, err := in.deps.Runner.Run(ctx, cmd)
		if err == nil {
			in.successf("%s complete", title)
		} else {
			in.errorf("%s failed", title)
		}
		return err
	}

	in.wiz.Stage(stage)
	in.wiz.TaskStart(title)
	var captured bytes.Buffer
	cmd.Stdout, cmd.Stderr = &captured, &captured

	stop := make(chan struct{})
	if poll {
		go in.pollServiceHealth(stop)
	}
	_, err := in.deps.Runner.Run(ctx, cmd)
	close(stop)
	in.wiz.TaskDone(err == nil)

	if err != nil {
		// Tear the wizard down so the tail prints as plain scrollback.
		in.wiz.Abort()
		in.wiz = nil
		lines := strings.Split(strings.TrimSpace(captured.String()), "\n")
		if len(lines) > failureLogTail {
			lines = lines[len(lines)-failureLogTail:]
		}
		for _, l := range lines {
			in.plainf("  %s", l)
		}
	}
	return err
}

// pollServiceHealth feeds the wizard a live per-service checklist while
// `up --wait` blocks (otherwise silent for up to ten minutes).
func (in *installer) pollServiceHealth(stop chan struct{}) {
	ctx := context.Background()
	for {
		select {
		case <-stop:
			return
		case <-time.After(2 * time.Second):
		}
		cmd := in.docker.Command(nil, "ps",
			"--filter", "label=com.docker.compose.project=onyx",
			"--format", "{{.Names}}\t{{.Status}}")
		res, err := in.deps.Runner.Run(ctx, cmd)
		if err != nil {
			continue
		}
		var rows []ui.ServiceRow
		ready := 0
		for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
			parts := strings.SplitN(line, "\t", 2)
			if len(parts) != 2 {
				continue
			}
			ok := strings.Contains(parts[1], "(healthy)") ||
				(strings.HasPrefix(parts[1], "Up") && !strings.Contains(parts[1], "health"))
			if ok {
				ready++
			}
			rows = append(rows, ui.ServiceRow{Name: strings.TrimPrefix(parts[0], "onyx-"), Ready: ok})
		}
		if len(rows) > 0 && in.wiz != nil {
			in.wiz.Services(rows)
			in.wiz.TaskExtra(fmt.Sprintf("%d/%d ready", ready, len(rows)))
		}
	}
}

func (in *installer) printSuccess(ctx context.Context, hostPort int) {
	url := fmt.Sprintf("http://localhost:%d", hostPort)
	headline := "Onyx is ready  →  " + ui.Accent(url)
	if in.opts.NoWait {
		headline = "Onyx containers started (still initializing — check: onyx-cli deploy status)"
	}
	lines := []string{
		headline,
		"",
		"First signup becomes the admin account: " + url + "/auth/signup",
		"Manage:  onyx-cli deploy status · stop · upgrade · uninstall",
	}
	if in.lite {
		lines = append(lines, "",
			"Lite mode: no Vespa/Redis/model servers or background workers.",
			"Connectors and RAG search are off; chat, tools, uploads, projects work.")
	}

	if in.wiz != nil {
		star := in.askStarQuestion()
		in.wiz.Stage(ui.StageDone)
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
	if in.prompt.AssumeDefaults {
		return false
	}
	if _, err := exec.LookPath("gh"); err != nil {
		return false
	}
	ok, err := in.confirmYN("Enjoying Onyx? Star the repo on GitHub?", true)
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

// composeFileNames returns the -f list. With autoDetect, previously
// downloaded overlays are picked up from disk so users don't have to repeat
// --lite/--include-craft for lifecycle commands (install.sh's
// build_compose_file_args true).
func (in *installer) composeFileNames(autoDetect bool) []string {
	files := []string{"docker-compose.yml"}
	liteName := filepath.Base(deployfiles.LiteOverlay.DestRel)
	craftName := filepath.Base(deployfiles.CraftOverlay.DestRel)
	if in.lite || (autoDetect && in.overlayOnDisk(liteName)) {
		files = append(files, liteName)
	}
	if in.craft || (autoDetect && in.overlayOnDisk(craftName)) {
		files = append(files, craftName)
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

// stopFallbackEnv supplies safe defaults for compose invocations that may run
// before .env is known-good (install.sh uses the same pair for shutdown).
func stopFallbackEnv() map[string]string {
	return map[string]string{"HOST_PORT": "3000", "IMAGE_TAG": "edge"}
}

func fileArgs(files []string) []string {
	args := make([]string, 0, 2*len(files))
	for _, f := range files {
		args = append(args, "-f", f)
	}
	return args
}
