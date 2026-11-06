package devstack

import (
	"context"
	"fmt"
	"os/exec"
	"time"
)

// RunForegroundService runs a service without background process management.
// Windows uses this path because stack locks and process groups are Unix-only.
func RunForegroundService(ctx context.Context, target Target, launch *Launch, slug string, opts ServiceOptions) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	ports := make(map[string]int, len(target.Ports)+1)
	for name, port := range target.Ports {
		ports[name] = port
	}
	port := opts.PreferredPort
	if port == 0 {
		port = ports[slug]
	}
	if port == 0 {
		switch slug {
		case "web":
			port = 3000
		case "api":
			port = 8080
		case "model":
			port = 9000
		}
	}
	if port < 1 || port > 65535 {
		return fmt.Errorf("invalid %s port %d", slug, port)
	}
	ports[slug] = port
	target.Ports = ports
	env, err := target.ServiceEnv()
	if err != nil {
		return err
	}
	sp, err := ResolveService(target.Root, launch, slug, ports, env)
	if err != nil {
		return err
	}
	args := opts.Args
	if len(args) > 0 && args[0] == "--" {
		args = args[1:]
	}
	if slug == "web" && len(args) > 0 {
		sp.Command = append(sp.Command, "--")
	}
	sp.Command = append(sp.Command, args...)
	if err := ctx.Err(); err != nil {
		return err
	}
	if opts.BeforeStart != nil {
		if err := opts.BeforeStart(ctx, sp); err != nil {
			return err
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	command := exec.CommandContext(ctx, sp.Command[0], sp.Command[1:]...)
	command.Dir, command.Env = sp.Dir, sp.Env
	command.Stdin, command.Stdout, command.Stderr = opts.IO.Stdin, opts.IO.Stdout, opts.IO.Stderr
	command.WaitDelay = 2 * time.Second
	return command.Run()
}
