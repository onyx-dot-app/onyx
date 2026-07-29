package dockercmd

import (
	"context"
)

// ProjectName is the compose project Onyx deployments run under, pinned by
// `name: onyx` in docker-compose.yml. Containers and volumes carry it as a
// label, which is what makes an install root movable and what lets docker
// find the stack without the compose files.
const ProjectName = "onyx"

// Compose invokes docker compose (plugin) or docker-compose (standalone),
// whichever is available, through the Docker sudo wrapper.
type Compose struct {
	docker     *Docker
	standalone bool
}

// DetectCompose finds a usable compose command, preferring the plugin
// (mirrors install.sh's detect_compose_cmd). Returns nil when neither works.
func DetectCompose(ctx context.Context, d *Docker) *Compose {
	if _, err := d.Runner.Run(ctx, Command{Name: "docker", Args: []string{"compose", "version"}}); err == nil {
		return &Compose{docker: d}
	}
	if _, err := d.Runner.Run(ctx, Command{Name: "docker-compose", Args: []string{"version"}}); err == nil {
		return &Compose{docker: d, standalone: true}
	}
	return nil
}

// TypeName describes the detected flavor for user-facing messages.
func (c *Compose) TypeName() string {
	if c.standalone {
		return "standalone"
	}
	return "plugin"
}

// Version returns the compose version, or "dev" when unparsable (non-standard
// builds report strings like "dev"; treated as recent enough, like install.sh).
func (c *Compose) Version(ctx context.Context) string {
	var probe Command
	if c.standalone {
		probe = Command{Name: "docker-compose", Args: []string{"--version"}}
	} else {
		probe = Command{Name: "docker", Args: []string{"compose", "version"}}
	}
	res, err := c.docker.Runner.Run(ctx, probe)
	if err != nil {
		return "dev"
	}
	if v := versionPattern.FindString(res.Stdout); v != "" {
		return v
	}
	return "dev"
}

// Command builds a compose invocation in dir: `[sudo env K=V] docker compose
// -f <file>... <args>` (or docker-compose). Env riding rules follow
// Docker.Command.
func (c *Compose) Command(dir string, env map[string]string, composeFiles []string, args ...string) Command {
	full := make([]string, 0, 2+2*len(composeFiles)+len(args))
	name := "docker"
	if c.standalone {
		name = "docker-compose"
	} else {
		full = append(full, "compose")
	}
	for _, f := range composeFiles {
		full = append(full, "-f", f)
	}
	full = append(full, args...)

	cmd := c.docker.commandFor(name, env, full...)
	cmd.Dir = dir
	return cmd
}

// commandFor generalizes Docker.Command to any binary needing the sudo/env
// wrapping treatment.
func (d *Docker) commandFor(name string, env map[string]string, args ...string) Command {
	if !d.sudo {
		return Command{Name: name, Args: args, Env: env}
	}
	sudoArgs := []string{"env"}
	for _, k := range sortedKeys(env) {
		sudoArgs = append(sudoArgs, k+"="+env[k])
	}
	sudoArgs = append(sudoArgs, name)
	sudoArgs = append(sudoArgs, args...)
	return Command{Name: "sudo", Args: sudoArgs}
}
