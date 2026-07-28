package install

import (
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
)

const banner = `
  ____
 / __ \
| |  | |_ __  _   ___  __
| |  | | '_ \| | | \ \/ /
| |__| | | | | |_| |>  <
 \____/|_| |_|\__, /_/\_\
               __/ |
              |___/
`

// RunInstall implements `deploy install` (and the install-onyx alias): fresh
// installs, and restart/update runs against an existing deployment.
func RunInstall(ctx context.Context, deps Deps, opts Options) error {
	in := newInstaller(deps, opts)
	in.totalSteps = 9
	in.lite = opts.Lite
	in.craft = opts.IncludeCraft
	return in.runInstall(ctx)
}

func (in *installer) runInstall(ctx context.Context) error {
	if in.opts.Lite && in.opts.IncludeCraft {
		return exitcodes.New(exitcodes.BadRequest,
			"--lite and --include-craft cannot be used together: Craft requires services (Vespa, Redis, background workers) that lite mode disables")
	}

	// Resolve the default deploy tag from the latest app release so users
	// land on a pinned, tested version; fall back to main/edge offline.
	defaultTag, lookupFailed := "edge", false
	if !in.opts.Local {
		if in.opts.Tag != "" {
			defaultTag = in.opts.Tag
		} else if tag, err := in.deps.Release.LatestAppTag(ctx); err == nil {
			defaultTag = tag
		} else {
			lookupFailed = true
		}
	}

	in.root = paths.Resolve(in.opts.Dir)

	if in.opts.DryRun {
		in.printPlan(defaultTag)
		return nil
	}

	if err := in.ensureDockerAndCompose(ctx); err != nil {
		return err
	}

	// ASCII banner + acknowledgment (mirrors install.sh).
	in.plainf("%s", banner)
	in.plainf("Welcome to the Onyx Installer")
	in.plainf("=============================")
	in.plainf("")
	if lookupFailed {
		in.warnf("Could not determine latest Onyx release — falling back to main / edge")
	}
	in.plainf("This command will:")
	in.plainf("1. Set up Onyx deployment files in '%s'", in.root.Dir)
	in.plainf("2. Check your system resources (Docker, memory, disk space)")
	in.plainf("3. Guide you through deployment options (version, mode)")
	in.plainf("")
	if err := in.prompt.AcknowledgeEnter("Please acknowledge and press Enter to continue..."); err != nil {
		return err
	}

	if err := in.verifyDocker(ctx); err != nil {
		return err
	}
	if err := in.verifyResources(ctx); err != nil {
		return err
	}

	in.stepf("Creating directory structure")
	if in.root.Source == paths.SourceLegacyCwd {
		in.infof("Managing existing install at %s (created by install.sh)", in.root.Dir)
	}
	for _, alt := range in.root.Ambiguous {
		in.warnf("Another Onyx install exists at %s — pass --dir to target it instead", alt)
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
	in.successf("Directory structure ready at %s", in.root.Dir)

	manifest, err := state.Load(in.root.Dir)
	if err != nil {
		return err
	}
	hadManifest := manifest != nil
	if manifest == nil {
		manifest = &state.Manifest{}
		if paths.IsInstall(in.root.Dir) {
			in.infof("No %s found — adopting this install; files not written by the CLI are treated as potentially customized", state.FileName)
		}
	}

	in.stepf("Preparing configuration files")
	if err := in.chooseMode(manifest.Mode); err != nil {
		return err
	}

	initialRef := ""
	if !in.opts.Local {
		initialRef = release.ConfigRef(defaultTag)
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
	in.successf("All configuration files ready")

	if err := in.checkComposeVersion(ctx); err != nil {
		return err
	}

	in.stepf("Setting up deployment configs")
	effectiveTag, err := in.configureEnv(ctx, defaultTag)
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

	in.stepf("Checking for available ports")
	hostPort := resources.FindAvailablePort(3000)
	if hostPort != 3000 {
		in.infof("Port 3000 is in use, found available port: %d", hostPort)
	} else {
		in.infof("Port 3000 is available")
	}
	in.successf("Using port %d for the web server", hostPort)

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

// ensureDockerAndCompose provisions Docker Engine and compose where install.sh
// does (Linux/WSL), starts Docker Desktop on macOS later during verification,
// and detect-and-instructs on native Windows.
func (in *installer) ensureDockerAndCompose(ctx context.Context) error {
	linuxLike := runtime.GOOS == "linux" || dockercmd.IsWSL()

	if !dockercmd.Installed() {
		switch {
		case linuxLike:
			in.infof("Docker is required but not installed.")
			ok, err := in.prompt.Confirm("Install Docker Engine? (Y/n) [default: Y] ", true)
			if err != nil {
				return err
			}
			if !ok {
				return exitcodes.New(exitcodes.General, "Docker is required to run Onyx")
			}
			if err := dockercmd.InstallDockerLinux(ctx, in.deps.Runner, in.deps.IOS.Out); err != nil {
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
		ok, err := in.prompt.Confirm("Install the Docker Compose plugin? (Y/n) [default: Y] ", true)
		if err != nil {
			return err
		}
		if !ok {
			return exitcodes.New(exitcodes.General, "Docker Compose is required to run Onyx")
		}
		if err := dockercmd.InstallComposePluginLinux(ctx, in.deps.Runner, in.deps.IOS.Out); err != nil {
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
		if err := dockercmd.EnsureDockerGroup(ctx, in.deps.Runner, in.deps.IOS.Out); err != nil {
			in.warnf("Could not add you to the docker group: %v", err)
		}
		in.infof("Using sudo for docker commands in this run.")
	}
	return nil
}

func (in *installer) verifyDocker(ctx context.Context) error {
	in.stepf("Verifying Docker installation")
	if v := in.docker.Version(ctx); v != "" {
		in.successf("Docker %s is installed", v)
	} else {
		in.successf("Docker is installed")
	}
	in.successf("Docker Compose %s is installed (%s)", in.compose.Version(ctx), in.compose.TypeName())

	if !in.docker.DaemonRunning(ctx) {
		if runtime.GOOS == "darwin" {
			in.infof("Docker daemon is not running. Starting Docker Desktop...")
			if err := dockercmd.StartDockerDesktopDarwin(ctx, in.docker, in.deps.IOS.Out, 120*time.Second); err != nil {
				return exitcodes.Newf(exitcodes.General, "%v", err)
			}
			in.successf("Docker Desktop is now running")
		} else {
			return exitcodes.New(exitcodes.General, "Docker daemon is not running. Please start Docker.")
		}
	} else {
		in.successf("Docker daemon is running")
	}
	return nil
}

func (in *installer) verifyResources(ctx context.Context) error {
	in.stepf("Verifying Docker resources")

	dockerInfo := ""
	if res, err := in.deps.Runner.Run(ctx, in.docker.Command(nil, "system", "info")); err == nil {
		dockerInfo = res.Stdout
	}
	memoryMB := resources.MemoryMB(dockerInfo)
	if memoryMB > 0 {
		if runtime.GOOS == "darwin" {
			in.infof("Docker memory allocation: %s", resources.FormatMemory(memoryMB))
		} else {
			in.infof("System memory: %s (Docker uses host memory directly)", resources.FormatMemory(memoryMB))
		}
	} else {
		in.warnf("Could not determine memory allocation")
	}

	diskGB := resources.DiskAvailableGB(".")
	if diskGB >= 0 {
		in.infof("Available disk space: %dGB", diskGB)
	} else {
		in.warnf("Could not determine available disk space")
	}

	ramWant, diskWant := expectedRAMGB, expectedDiskGB
	if in.lite {
		ramWant, diskWant = expectedRAMGBLite, expectedDiskGBLite
	}
	warning := false
	if memoryMB > 0 && memoryMB < ramWant*1024 {
		in.warnf("Less than %dGB RAM available (found: %s)", ramWant, resources.FormatMemory(memoryMB))
		warning = true
	}
	if diskGB >= 0 && diskGB < diskWant {
		in.warnf("Less than %dGB disk space available (found: %dGB)", diskWant, diskGB)
		warning = true
	}
	if warning {
		in.plainf("")
		in.warnf("Onyx recommends at least %dGB RAM and %dGB disk space for optimal performance in standard mode.", ramWant, diskWant)
		in.warnf("Lite mode requires less resources (1-4GB RAM, 8-16GB disk depending on usage), but does not include a vector database.")
		in.plainf("")
		cont, err := in.prompt.Confirm("Do you want to continue anyway? (Y/n): ", true)
		if err != nil {
			return err
		}
		if !cont {
			return exitcodes.New(exitcodes.General, "Installation cancelled. Please allocate more resources and try again.")
		}
		in.infof("Proceeding with installation despite resource limitations...")
	}
	return nil
}

// chooseMode runs the lite-vs-standard prompt unless --lite already decided
// it. Lite is the default for new installs (matching install.sh); an existing
// install defaults to its recorded mode, so a --no-prompt restart cannot
// silently switch a standard deployment to lite (an install.sh footgun).
func (in *installer) chooseMode(prevMode state.Mode) error {
	if in.lite {
		in.infof("Deployment mode: Lite (set via --lite flag)")
		return nil
	}
	if in.craft {
		// Craft implies standard mode; the flag conflict was checked early.
		return nil
	}
	def := "1"
	if prevMode == state.ModeStandard {
		def = "2"
	}
	in.infof("Which deployment mode would you like?")
	in.plainf("")
	in.plainf("  1) Lite      - Minimal deployment (no OpenSearch, Redis, or model servers)")
	in.plainf("                  LLM chat, tools, file uploads, and Projects still work")
	in.plainf("  2) Standard  - Full deployment with search, connectors, and RAG")
	in.plainf("")
	choice, err := in.prompt.Ask(fmt.Sprintf("Choose a mode (1 or 2) [default: %s]: ", def), def)
	if err != nil {
		return err
	}
	in.plainf("")
	if choice == "2" {
		in.infof("Selected: Standard mode")
	} else {
		in.lite = true
		in.infof("Selected: Lite mode")
	}
	return nil
}

func (in *installer) checkComposeVersion(ctx context.Context) error {
	composeVersion := in.compose.Version(ctx)
	if composeVersion == "dev" {
		return nil
	}
	have, ok := version.Parse(composeVersion)
	minimum, _ := version.Parse(minComposeVersion)
	if !ok || !have.LessThan(minimum) {
		return nil
	}
	in.warnf("Docker Compose version %s is older than %s", composeVersion, minComposeVersion)
	in.plainf("")
	in.warnf("The docker-compose.yml file uses the newer env_file format that requires Docker Compose %s or later.", minComposeVersion)
	in.infof("Upgrade Docker Compose (https://docs.docker.com/compose/install/) or manually flatten the env_file sections.")
	in.plainf("")
	cont, err := in.prompt.Confirm("Do you want to continue anyway? (Y/n): ", true)
	if err != nil {
		return err
	}
	if !cont {
		return exitcodes.New(exitcodes.General, "Installation cancelled. Please upgrade Docker Compose and re-run.")
	}
	in.infof("Proceeding despite the Docker Compose version mismatch...")
	return nil
}

// configureEnv creates or updates deployment/.env and returns the effective
// image tag.
func (in *installer) configureEnv(ctx context.Context, defaultTag string) (string, error) {
	envPath := filepath.Join(in.root.Dir, "deployment", ".env")
	existing, err := os.ReadFile(envPath)
	switch {
	case err == nil:
		return in.reconfigureExistingEnv(ctx, envPath, string(existing), defaultTag)
	case os.IsNotExist(err):
		return in.createFreshEnv(envPath, defaultTag)
	default:
		return "", fmt.Errorf("failed to read %s: %w", envPath, err)
	}
}

func (in *installer) createFreshEnv(envPath, defaultTag string) (string, error) {
	in.infof("No existing .env file found. Setting up new deployment...")
	in.plainf("")

	tag := in.opts.Tag
	if tag == "" {
		in.infof("Which tag would you like to deploy?")
		in.plainf("")
		in.plainf("• Press Enter for %s (recommended)", defaultTag)
		in.plainf("• Type a specific tag (e.g., v1.2.3)")
		in.plainf("")
		var err error
		tag, err = in.prompt.Ask(fmt.Sprintf("Enter tag [default: %s]: ", defaultTag), defaultTag)
		if err != nil {
			return "", err
		}
		in.plainf("")
	}
	if tag == "edge" {
		in.infof("Selected: edge (latest nightly)")
	} else {
		in.infof("Selected: %s", tag)
	}

	template, err := os.ReadFile(filepath.Join(in.root.Dir, "deployment", "env.template"))
	if err != nil {
		return "", fmt.Errorf("failed to read env.template: %w", err)
	}
	env := string(template)

	in.infof("Creating .env file with your selections...")
	env = SetVar(env, "IMAGE_TAG", tag)

	if in.lite {
		// MinIO never starts in lite mode and the overlay forces the
		// postgres file store at runtime; align .env so it isn't misleading.
		env = SetVar(env, "COMPOSE_PROFILES", "")
		env = SetVar(env, "FILE_STORE_BACKEND", "postgres")
		in.successf("Cleared COMPOSE_PROFILES and set FILE_STORE_BACKEND=postgres for lite mode")
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
			in.plainf("")
			in.plainf("%s", craftSecurityWarning)
			in.plainf("")
		} else {
			in.infof("Image tag %s predates the docker sandbox backend (v4.0.6+); using SANDBOX_BACKEND=%s.", tag, backend)
		}
	} else {
		in.infof("Onyx Craft disabled (use --include-craft to enable)")
	}

	if err := os.WriteFile(envPath, []byte(env), 0600); err != nil {
		return "", fmt.Errorf("failed to write .env: %w", err)
	}
	in.successf(".env file created with your preferences")
	in.plainf("")
	in.infof("You can customize %s later for AI models, domains, and more.", envPath)
	in.plainf("")
	return tag, nil
}

func (in *installer) reconfigureExistingEnv(ctx context.Context, envPath, env, defaultTag string) (string, error) {
	if err := in.guardServicesStopped(ctx); err != nil {
		return "", err
	}

	update := false
	tag := in.opts.Tag
	if tag != "" {
		// An explicit --tag on an existing install is an update request.
		update = tag != Var(env, "IMAGE_TAG")
	} else {
		in.infof("Existing .env file found. What would you like to do?")
		in.plainf("")
		in.plainf("• Press Enter to restart with current configuration")
		in.plainf("• Type 'update' to update to a newer version")
		in.plainf("  (scriptable equivalent: onyx-cli deploy upgrade --tag <tag>)")
		in.plainf("")
		choice, err := in.prompt.Ask("Choose an option [default: restart]: ", "")
		if err != nil {
			return "", err
		}
		in.plainf("")
		if choice == "update" {
			update = true
			tag, err = in.prompt.Ask(fmt.Sprintf("Enter tag [default: %s]: ", defaultTag), defaultTag)
			if err != nil {
				return "", err
			}
			in.plainf("")
		}
	}

	if update {
		in.infof("Updating configuration for version %s...", tag)
		env = SetVar(env, "IMAGE_TAG", tag)
		in.successf("Updated IMAGE_TAG to %s in .env file", tag)
	} else {
		in.infof("Keeping existing configuration...")
		in.successf("Will restart with current settings")
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

// guardServicesStopped refuses to reconfigure while containers are up. The
// replacement message points at a command that actually exists after a
// curl|bash install — unlike install.sh's "./install.sh --shutdown".
func (in *installer) guardServicesStopped(ctx context.Context) error {
	files := in.composeFileNames(true)
	cmd := in.compose.Command(in.deploymentDir(), stopFallbackEnv(), files, "ps", "-q")
	res, err := in.deps.Runner.Run(ctx, cmd)
	if err != nil || strings.TrimSpace(res.Stdout) == "" {
		return nil
	}
	in.errorf("Onyx services are currently running!")
	in.plainf("")
	in.infof("To make configuration changes, you must first shut down the services:")
	in.plainf("   onyx-cli deploy stop")
	in.plainf("")
	in.infof("Then re-run this command to make your changes.")
	return exitcodes.New(exitcodes.General, "services are running")
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

	in.stepf("Pulling Docker images")
	in.infof("This may take several minutes depending on your internet connection...")
	pullArgs := []string{"pull"}
	if !in.opts.Verbose {
		pullArgs = append(pullArgs, "--quiet")
	}
	pull := in.compose.Command(dir, env, files, pullArgs...)
	pull.Stdout, pull.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
	if _, err := in.deps.Runner.Run(ctx, pull); err != nil {
		in.errorf("Failed to download Docker images")
		return exitcodes.Newf(exitcodes.General, "docker compose pull failed: %v", err)
	}
	in.successf("Docker images downloaded successfully")

	in.stepf("Starting Onyx services")
	upArgs := []string{"up", "-d"}
	if floating {
		in.infof("Using '%s' tag - force pulling latest images and recreating containers...", tag)
		upArgs = append(upArgs, "--pull", "always", "--force-recreate")
	}
	if !in.opts.NoWait {
		in.infof("Waiting up to %ds for all services to become healthy...", waitTimeoutSeconds)
		upArgs = append(upArgs, "--wait", "--wait-timeout", fmt.Sprintf("%d", waitTimeoutSeconds))
	}
	in.plainf("")
	up := in.compose.Command(dir, env, files, upArgs...)
	up.Stdout, up.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
	if _, err := in.deps.Runner.Run(ctx, up); err != nil {
		in.errorf("Failed to start Onyx services")
		in.plainf("")
		in.infof("Current container status:")
		ps := in.compose.Command(dir, env, files, "ps")
		ps.Stdout, ps.Stderr = in.deps.IOS.Out, in.deps.IOS.ErrOut
		_, _ = in.deps.Runner.Run(ctx, ps)
		in.plainf("")
		in.infof("Check the logs of any unhealthy service:")
		in.plainf("  onyx-cli deploy status")
		in.plainf("  (cd %q && docker compose %s logs <service>)", dir, strings.Join(fileArgs(files), " "))
		in.plainf("")
		in.infof("If the issue persists, please contact: founders@onyx.app")
		return exitcodes.Newf(exitcodes.General, "docker compose up failed: %v", err)
	}
	return nil
}

func (in *installer) printSuccess(ctx context.Context, hostPort int) {
	in.stepf("Installation Complete!")
	in.plainf("")
	if in.opts.NoWait {
		in.plainf("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
		in.plainf("   ⚠️  Onyx containers started  ⚠️")
		in.plainf("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
		in.infof("Services may still be initializing. Check status with: onyx-cli deploy status")
	} else {
		in.plainf("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
		in.plainf("   🎉 Onyx service is ready! 🎉")
		in.plainf("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	}
	in.plainf("")
	in.infof("Access Onyx at:")
	in.plainf("   http://localhost:%d", hostPort)
	in.plainf("")
	in.infof("If authentication is enabled, you can create your admin account here:")
	in.plainf("   • Visit http://localhost:%d/auth/signup to create your admin account", hostPort)
	in.plainf("   • The first user created will automatically have admin privileges")
	in.plainf("")
	if in.lite {
		in.infof("Running in Lite mode — the following services are NOT started:")
		in.plainf("  • Vespa (vector database)")
		in.plainf("  • Redis (cache)")
		in.plainf("  • Model servers (embedding/inference)")
		in.plainf("  • Background workers (Celery)")
		in.plainf("")
		in.infof("Connectors and RAG search are disabled. LLM chat, tools, user file")
		in.infof("uploads, Projects, Agent knowledge, and code interpreter still work.")
		in.plainf("")
	}
	in.infof("Manage this deployment with: onyx-cli deploy status | stop | upgrade | uninstall")
	in.infof("Refer to the README in the %s directory for more information.", in.root.Dir)
	in.plainf("")
	in.infof("For help or issues, contact: founders@onyx.app")
	in.plainf("")
	in.starPrompt(ctx)
}

// starPrompt ports install.sh's GitHub star prompt: only when interactive and
// the gh CLI is available.
func (in *installer) starPrompt(ctx context.Context) {
	if in.prompt.AssumeDefaults {
		return
	}
	if _, err := exec.LookPath("gh"); err != nil {
		return
	}
	ok, err := in.prompt.Confirm("Enjoying Onyx? Star the repo on GitHub? [Y/n] ", true)
	if err != nil || !ok {
		return
	}
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
