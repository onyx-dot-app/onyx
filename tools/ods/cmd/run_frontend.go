package cmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

func runWebDev(args []string) error {
	port, forwarded, err := frontendArgs(args)
	if err != nil {
		return err
	}
	target, err := resolveRuntimeTarget()
	if err != nil {
		return err
	}
	opts := devstack.ServiceOptions{
		PreferredPort: port, Args: forwarded, IO: devstack.ServiceIO{Stdin: os.Stdin, Stdout: os.Stdout, Stderr: os.Stderr},
		RequireAPI: true, LockWait: 30 * time.Second, StopTimeout: 20 * time.Second,
		BeforeStart: func(ctx context.Context, _ devstack.Spec) error {
			return prepareWebDirOutputContext(ctx, filepath.Join(target.Root, "web"), os.Stdout)
		},
	}
	if _, _, err := devstack.PrepareEnvFiles(target.Root); err != nil {
		return err
	}
	launch, err := devstack.LoadLaunch(filepath.Join(target.Root, ".vscode", "launch.json"))
	if err != nil {
		return err
	}
	if runtime.GOOS == "windows" {
		return devstack.RunForegroundService(context.Background(), target, launch, "web", opts)
	}
	preview, err := devstack.Open(target.Root, target.Project, devstack.Frontend)
	if err != nil {
		return err
	}
	preview.Registry = runtimeRegistry()
	if target.Managed {
		owner := stackForTarget(target)
		st, err := owner.Status()
		if err != nil {
			return err
		}
		if st != nil && st.Root == target.Root {
			for _, rec := range st.Services {
				if rec.Slug == "web" && rec.State == devstack.StateRunning {
					preview = owner
					break
				}
			}
		}
	}
	return preview.RunService(context.Background(), target, launch, "web", opts)
}

func frontendArgs(args []string) (int, []string, error) {
	port := 0
	var forwarded []string
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if i == 0 && arg == "--" {
			continue
		}
		value := ""
		switch {
		case arg == "--port" || arg == "-p":
			i++
			if i >= len(args) {
				return 0, nil, fmt.Errorf("%s requires a port", arg)
			}
			value = args[i]
		case strings.HasPrefix(arg, "--port="):
			value = strings.TrimPrefix(arg, "--port=")
		case strings.HasPrefix(arg, "-p") && len(arg) > 2:
			value = strings.TrimPrefix(strings.TrimPrefix(arg, "-p"), "=")
		default:
			forwarded = append(forwarded, arg)
			continue
		}
		parsed, err := strconv.Atoi(value)
		if err != nil || parsed < 1 || parsed > 65535 {
			return 0, nil, fmt.Errorf("invalid web port %q", value)
		}
		if port != 0 && port != parsed {
			return 0, nil, fmt.Errorf("specify one web port")
		}
		port = parsed
	}
	return port, forwarded, nil
}
