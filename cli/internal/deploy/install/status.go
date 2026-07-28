package install

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
)

// Status is the machine-readable `deploy status --json` payload.
type Status struct {
	Installed    bool      `json:"installed"`
	Dir          string    `json:"dir"`
	Source       string    `json:"source"`
	ManifestTag  string    `json:"manifest_tag,omitempty"`
	EnvTag       string    `json:"env_tag,omitempty"`
	RunningTag   string    `json:"running_tag,omitempty"`
	Mode         string    `json:"mode,omitempty"`
	IncludeCraft bool      `json:"include_craft"`
	AccessURL    string    `json:"access_url,omitempty"`
	Services     []Service `json:"services"`
	Healthy      bool      `json:"healthy"`
}

// Service is one container of the deployment.
type Service struct {
	Name   string `json:"name"`
	Image  string `json:"image"`
	Status string `json:"status"`
}

// RunStatus implements `deploy status`. Read-only: it never provisions or
// mutates anything. Exit codes make it usable as a probe: 0 when installed
// with all services up and none unhealthy, NotAvailable when no install
// exists, General when stopped or degraded.
func RunStatus(ctx context.Context, deps Deps, opts Options, jsonOut bool) error {
	in := newInstaller(deps, opts)
	return in.runStatus(ctx, jsonOut)
}

func (in *installer) runStatus(ctx context.Context, jsonOut bool) error {
	in.root = paths.Resolve(in.opts.Dir)
	st := Status{Dir: in.root.Dir, Source: string(in.root.Source)}

	if !paths.IsInstall(in.root.Dir) {
		if jsonOut {
			return in.emitStatus(st, exitcodes.NotAvailable)
		}
		in.infof("No Onyx install found at %s", in.root.Dir)
		for _, alt := range in.root.Ambiguous {
			in.infof("(another install exists at %s — pass --dir to inspect it)", alt)
		}
		in.infof("Install one with: onyx-cli deploy install")
		return exitcodes.New(exitcodes.NotAvailable, "not installed")
	}
	st.Installed = true

	if manifest, err := state.Load(in.root.Dir); err != nil {
		in.warnf("%v", err)
	} else if manifest != nil {
		st.ManifestTag = manifest.InstalledTag
		st.Mode = string(manifest.Mode)
		st.IncludeCraft = manifest.IncludeCraft
	}
	if env, err := os.ReadFile(filepath.Join(in.deploymentDir(), ".env")); err == nil {
		st.EnvTag = Var(string(env), "IMAGE_TAG")
	}
	if st.Mode == "" {
		st.Mode = "standard"
		if in.overlayOnDisk(filepath.Base(deployfiles.LiteOverlay.DestRel)) {
			st.Mode = "lite"
		}
	}

	st.Services, st.RunningTag, st.AccessURL = in.inspectContainers(ctx)

	up, unhealthy := 0, 0
	for _, s := range st.Services {
		if strings.HasPrefix(s.Status, "Up") {
			up++
		}
		if strings.Contains(s.Status, "(unhealthy)") {
			unhealthy++
		}
	}
	st.Healthy = up > 0 && up == len(st.Services) && unhealthy == 0

	if jsonOut {
		code := exitcodes.Success
		if !st.Healthy {
			code = exitcodes.General
		}
		return in.emitStatus(st, code)
	}

	in.plainf("Onyx deployment at %s (%s)", st.Dir, st.Source)
	in.plainf("  Mode: %s%s", st.Mode, map[bool]string{true: " + craft", false: ""}[st.IncludeCraft])
	in.plainf("  Version (manifest): %s", orUnknown(st.ManifestTag))
	in.plainf("  Version (.env):     %s", orUnknown(st.EnvTag))
	in.plainf("  Version (running):  %s", orUnknown(st.RunningTag))
	if drift(st.ManifestTag, st.EnvTag, st.RunningTag) {
		in.warnf("Version drift detected — the manifest, .env, and running containers disagree.")
		in.infof("A restart applies .env: onyx-cli deploy stop && onyx-cli deploy install")
	}
	in.plainf("")
	if len(st.Services) == 0 {
		in.infof("No containers found (deployment is stopped)")
		return exitcodes.New(exitcodes.General, "deployment is stopped")
	}
	for _, s := range st.Services {
		in.plainf("  %-40s %s", s.Name, s.Status)
	}
	in.plainf("")
	if st.AccessURL != "" {
		in.infof("Access Onyx at: %s", st.AccessURL)
	}
	if unhealthy > 0 {
		in.warnf("%d service(s) unhealthy. Check logs with:", unhealthy)
		in.plainf("  (cd %q && docker compose logs <service>)", in.deploymentDir())
		return exitcodes.New(exitcodes.General, "deployment is degraded")
	}
	if up < len(st.Services) {
		in.warnf("%d of %d containers are not running", len(st.Services)-up, len(st.Services))
		return exitcodes.New(exitcodes.General, "deployment is partially stopped")
	}
	in.successf("All %d services are up", up)
	return nil
}

func (in *installer) emitStatus(st Status, code exitcodes.Code) error {
	data, err := json.MarshalIndent(st, "", "  ")
	if err != nil {
		return err
	}
	fmt.Fprintln(in.deps.IOS.Out, string(data))
	if code == exitcodes.Success {
		return nil
	}
	return exitcodes.New(code, "see status output")
}

// inspectContainers lists the project's containers via the compose project
// label (the project name is pinned to "onyx" in the compose file, so this
// works regardless of directory names or which overlays are active).
func (in *installer) inspectContainers(ctx context.Context) (services []Service, runningTag, accessURL string) {
	if !dockercmd.Installed() {
		return nil, "", ""
	}
	in.docker.RefreshSudo(ctx)
	cmd := in.docker.Command(nil, "ps", "-a",
		"--filter", "label=com.docker.compose.project=onyx",
		"--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}")
	res, err := in.deps.Runner.Run(ctx, cmd)
	if err != nil {
		in.warnf("Could not query docker: %v", err)
		return nil, "", ""
	}
	for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
		if line == "" {
			continue
		}
		parts := strings.SplitN(line, "\t", 4)
		if len(parts) < 3 {
			continue
		}
		svc := Service{Name: parts[0], Image: parts[1], Status: parts[2]}
		services = append(services, svc)
		if runningTag == "" && strings.HasPrefix(svc.Status, "Up") {
			if idx := strings.LastIndex(svc.Image, ":"); idx != -1 {
				runningTag = svc.Image[idx+1:]
			}
		}
		if accessURL == "" && len(parts) == 4 && strings.HasPrefix(svc.Status, "Up") {
			if port := publishedHostPort(parts[3]); port != "" {
				accessURL = "http://localhost:" + port
			}
		}
	}
	return services, runningTag, accessURL
}

var hostPortPattern = regexp.MustCompile(`(?:0\.0\.0\.0|\[::\]|127\.0\.0\.1):(\d+)->`)

// publishedHostPort extracts the first published host port from a docker ps
// Ports column (e.g. "0.0.0.0:3000->80/tcp, [::]:3000->80/tcp").
func publishedHostPort(ports string) string {
	m := hostPortPattern.FindStringSubmatch(ports)
	if m == nil {
		return ""
	}
	return m[1]
}

// drift reports whether the known version numbers disagree (unknowns are
// skipped rather than counted as drift).
func drift(tags ...string) bool {
	known := ""
	for _, t := range tags {
		if t == "" {
			continue
		}
		if known == "" {
			known = t
			continue
		}
		if t != known {
			return true
		}
	}
	return false
}

func orUnknown(s string) string {
	if s == "" {
		return "unknown"
	}
	return s
}
