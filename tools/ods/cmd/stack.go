package cmd

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/alembic"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// exitHook ends the process with a code after the status was printed. It
// goes through logrus so its exit handlers run; tests replace it.
var exitHook = func(code int) { log.StandardLogger().Exit(code) }

// stackOptions holds the flags shared by the lifecycle subcommands.
type stackOptions struct {
	devstack.Options
	JSON bool
}

// NewStackCommand creates the "stack" command that runs the local dev stack
// of the current worktree.
func NewStackCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stack",
		Short: "Run the local dev stack of this worktree",
		Long: `Run the local Onyx dev stack from a source checkout: Compose infrastructure,
migrations, and the application services from .vscode/launch.json as
background processes.

Every worktree gets its own Compose project, its own host ports, and its own
state under its git metadata (git rev-parse --git-path ods-stack). Port leases
are shared across worktrees in ` + filepath.Join(paths.DataDir(), "stack") + `
so a worktree keeps its ports across restarts. A lifecycle command takes the
worktree's lock, so two agents running "up" at once converge on one stack.

Profiles:
  minimal  Web Server and API Server
  default  minimal plus the primary, light, beat, docfetching, docprocessing
           and user_file_processing Celery workers
  full     every service in the "Run All Onyx Services" compound

The model server comes from Compose; --local-model-server runs it from the
checkout instead, for model server changes.

Examples:
  ods stack up
  ods stack up --profile full --json
  ods stack status --json
  ods stack logs api --follow
  ods stack stop
  ods stack down`,
	}

	cmd.AddCommand(newStackLifecycleCommand("up", "Set up the worktree, start infrastructure, migrate and start the services"))
	cmd.AddCommand(newStackLifecycleCommand("start", "Start or reconcile the services against running infrastructure"))
	cmd.AddCommand(newStackLifecycleCommand("restart", "Stop the services and start them again"))
	cmd.AddCommand(newStackStopCommand("stop", "Stop the services, keep the infrastructure"))
	cmd.AddCommand(newStackStopCommand("down", "Stop the services and the infrastructure (volumes are kept)"))
	cmd.AddCommand(newStackStatusCommand())
	cmd.AddCommand(newStackLogsCommand())
	cmd.AddCommand(newStackPlanCommand())
	return cmd
}

func addStackPlanFlags(cmd *cobra.Command, opts *stackOptions) {
	cmd.Flags().StringVar(&opts.Profile, "profile", devstack.ProfileDefault, "Services to run: "+strings.Join(devstack.Profiles, ", "))
	cmd.Flags().BoolVar(&opts.LocalModelServer, "local-model-server", false, "Run the model server from the checkout instead of Compose")
}

func newStackLifecycleCommand(name, short string) *cobra.Command {
	opts := &stackOptions{}
	cmd := &cobra.Command{
		Use:   name,
		Short: short,
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			stack, provider := openStack()
			ctx := context.Background()
			var status *devstack.Status
			var err error
			switch name {
			case "up":
				status, err = stack.Up(ctx, provider, opts.Options)
			case "start":
				status, err = stack.Start(ctx, provider, opts.Options)
			default:
				status, err = stack.Restart(ctx, provider, opts.Options)
			}
			if err != nil && status == nil {
				// Setup failed before the services were reached; report the
				// recorded phase and errors so the caller still gets a status.
				if recorded, serr := stack.Status(); serr == nil && recorded != nil {
					status = recorded
				}
			}
			if status != nil {
				printStackStatus(status, opts.JSON)
			}
			if err != nil {
				log.Error(err)
				if status != nil && status.Phase != devstack.PhaseFailed {
					exitHook(2)
				}
				exitHook(1)
			}
		},
	}
	addStackPlanFlags(cmd, opts)
	cmd.Flags().DurationVar(&opts.ReadyTimeout, "timeout", 3*time.Minute, "How long to wait for the services to become healthy")
	cmd.Flags().DurationVar(&opts.LockWait, "lock-wait", 10*time.Minute, "How long to wait for another lifecycle command on this worktree")
	cmd.Flags().DurationVar(&opts.StopTimeout, "stop-timeout", 20*time.Second, "Grace period before a stale service is killed")
	cmd.Flags().BoolVar(&opts.SkipPrepare, "skip-prepare", false, "Skip uv sync and bun install")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "Print the status as JSON")
	return cmd
}

func newStackStopCommand(name, short string) *cobra.Command {
	opts := &stackOptions{}
	cmd := &cobra.Command{
		Use:   name,
		Short: short,
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			stack, provider := openStack()
			var err error
			if name == "down" {
				err = stack.Down(context.Background(), provider, opts.Options)
			} else {
				err = stack.Stop(context.Background(), opts.Options)
			}
			if err != nil {
				log.Fatal(err)
			}
			log.Infof("Stack %s: services stopped", name)
		},
	}
	cmd.Flags().DurationVar(&opts.StopTimeout, "timeout", 20*time.Second, "Grace period before a service is killed")
	cmd.Flags().DurationVar(&opts.LockWait, "lock-wait", 10*time.Minute, "How long to wait for another lifecycle command on this worktree")
	return cmd
}

func newStackStatusCommand() *cobra.Command {
	var asJSON bool
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show the services, ports, URLs and health (exit 0 ready, 2 not ready, 1 no stack)",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			stack, _ := openStack()
			status, err := stack.Status()
			if err != nil {
				log.Fatal(err)
			}
			if status == nil {
				if asJSON {
					fmt.Println("null")
				} else {
					log.Infof("No dev stack has been started in %s", stack.Root)
				}
				os.Exit(1)
			}
			printStackStatus(status, asJSON)
			if !status.Ready {
				exitHook(2)
			}
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "Print the status as JSON")
	return cmd
}

func newStackLogsCommand() *cobra.Command {
	var lines int
	var follow bool
	cmd := &cobra.Command{
		Use:   "logs [service...]",
		Short: "Show service logs (names as in `ods stack status`)",
		Args:  cobra.ArbitraryArgs,
		Run: func(cmd *cobra.Command, args []string) {
			stack, _ := openStack()
			if err := runStackLogs(stack, args, lines, follow); err != nil {
				log.Fatal(err)
			}
		},
	}
	cmd.Flags().IntVar(&lines, "lines", 80, "Lines to show from the end of each log")
	cmd.Flags().BoolVar(&follow, "follow", false, "Follow the logs")
	return cmd
}

func newStackPlanCommand() *cobra.Command {
	opts := &stackOptions{}
	cmd := &cobra.Command{
		Use:   "plan",
		Short: "Print the services a profile would run, without starting them",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			stack, provider := openStack()
			st, err := stack.ReadState()
			if err != nil {
				log.Fatal(err)
			}
			ports := map[string]int{}
			if st != nil {
				ports = st.Ports
			}
			specs, err := provider.Plan(stack.Root, ports, devstack.Env{}, opts.WithDefaults())
			if err != nil {
				log.Fatal(err)
			}
			for _, sp := range specs {
				fmt.Printf("%s (%s): cd %s && %s\n", sp.Slug, sp.Name, sp.Dir, strings.Join(sp.Command, " "))
			}
		},
	}
	addStackPlanFlags(cmd, opts)
	return cmd
}

// openStack resolves the stack of the current worktree and its provider.
// The Compose project is unique per worktree unless --project overrides it.
func openStack() (*devstack.Stack, *stackProvider) {
	cwd, err := os.Getwd()
	if err != nil {
		log.Fatal(err)
	}
	stack, err := devstack.Open(cwd, flagProjectName())
	if err != nil {
		log.Fatal(err)
	}
	stack.Registry = &devstack.Registry{Dir: filepath.Join(paths.DataDir(), "stack")}
	docker.SetProjectFlags(stack.Project)
	return stack, &stackProvider{stack: stack}
}

func printStackStatus(status *devstack.Status, asJSON bool) {
	if asJSON {
		data, err := json.MarshalIndent(status, "", "  ")
		if err != nil {
			log.Fatal(err)
		}
		fmt.Println(string(data))
		return
	}
	fmt.Printf("project: %s\nprofile: %s\nphase:   %s\nready:   %t\n", status.Project, status.Profile, status.Phase, status.Ready)
	names := make([]string, 0, len(status.URLs))
	for name := range status.URLs {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		fmt.Printf("%-8s %s\n", name+":", status.URLs[name])
	}
	for _, svc := range status.Services {
		detail := ""
		switch {
		case svc.State == devstack.StateSkipped:
			detail = svc.Reason
		case svc.Healthy != nil && *svc.Healthy:
			detail = "healthy"
		case svc.Healthy != nil:
			detail = "unhealthy"
		}
		fmt.Printf("%-8s %-28s pid %-7d %s\n", svc.State, svc.Slug, svc.PID, detail)
		if svc.LogTail != "" {
			fmt.Printf("         log: %s\n", svc.Log)
			for _, line := range strings.Split(svc.LogTail, "\n") {
				fmt.Printf("         | %s\n", line)
			}
		}
	}
	for _, e := range status.Errors {
		fmt.Printf("error:   %s\n", e)
	}
}

func runStackLogs(stack *devstack.Stack, services []string, lines int, follow bool) error {
	st, err := stack.ReadState()
	if err != nil {
		return err
	}
	if st == nil {
		return errors.New("no dev stack has been started in this worktree")
	}
	var files []string
	for _, rec := range st.Services {
		if rec.Log == "" {
			continue
		}
		if len(services) == 0 {
			files = append(files, rec.Log)
			continue
		}
		for _, want := range services {
			if rec.Slug == want || rec.Name == want {
				files = append(files, rec.Log)
			}
		}
	}
	if len(files) == 0 {
		return fmt.Errorf("no logs for %s", strings.Join(services, ", "))
	}
	args := []string{"-n", fmt.Sprint(lines)}
	if follow {
		args = append(args, "-F")
	}
	tail := exec.Command("tail", append(args, files...)...)
	tail.Stdout = os.Stdout
	tail.Stderr = os.Stderr
	return tail.Run()
}

// stackProvider runs the host-specific steps with the existing ods
// commands: compose, env and alembic.
type stackProvider struct {
	stack *devstack.Stack
}

func (p *stackProvider) Prepare(ctx context.Context) error {
	for _, tool := range []string{"uv", "bun", "docker"} {
		if _, err := exec.LookPath(tool); err != nil {
			return fmt.Errorf("%s is not installed", tool)
		}
	}
	if err := runInDir(ctx, p.stack.Root, "docker", "info"); err != nil {
		return fmt.Errorf("docker is not running: %w", err)
	}
	log.Info("Syncing Python dependencies (uv sync --frozen)...")
	if err := runInDir(ctx, p.stack.Root, "uv", "sync", "--frozen"); err != nil {
		return err
	}
	prepareWebDirOutput(filepath.Join(p.stack.Root, "web"), os.Stderr)
	return nil
}

func runInDir(ctx context.Context, dir, name string, args ...string) error {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = dir
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s %s: %w", name, strings.Join(args, " "), err)
	}
	return nil
}

// InfraPorts requests one durable host port per exposed infrastructure
// port. A container that already runs keeps its mapped port.
func (p *stackProvider) InfraPorts() ([]devstack.PortRequest, error) {
	var reqs []devstack.PortRequest
	for _, svc := range docker.InfraServices {
		container := docker.ContainerName(p.stack.Project, svc.Name)
		for _, spec := range svc.Ports {
			req := devstack.PortRequest{Name: spec.ComposeVar, Preferred: spec.DefaultHost}
			if port, err := docker.GetHostPort(container, spec.ContainerPort); err == nil {
				req.Fixed = port
			}
			reqs = append(reqs, req)
		}
	}
	return reqs, nil
}

func (p *stackProvider) AppPorts(opts devstack.Options) []devstack.PortRequest {
	return devstack.AppPortRequests(opts)
}

// ComposeUp starts the infrastructure on the leased ports. With a local
// model server the Compose inference server stays down.
func (p *stackProvider) ComposeUp(ctx context.Context, ports map[string]int, opts devstack.Options) error {
	composePorts := map[string]string{}
	for _, svc := range docker.InfraServices {
		for _, spec := range svc.Ports {
			if port, ok := ports[spec.ComposeVar]; ok {
				composePorts[spec.ComposeVar] = fmt.Sprint(port)
			}
		}
	}
	composeOpts := &ComposeOptions{Wait: true, Infra: true, Ports: composePorts, Output: os.Stderr}
	if opts.LocalModelServer {
		composeOpts.ExcludeServices = []string{"inference_model_server"}
		ids, err := exec.CommandContext(ctx, "docker", "ps",
			"--filter", "label=com.docker.compose.project="+p.stack.Project,
			"--filter", "label=com.docker.compose.service=inference_model_server",
			"--format", "{{.ID}}").Output()
		if err != nil {
			return fmt.Errorf("find this stack's inference container: %w", err)
		}
		if containers := strings.Fields(string(ids)); len(containers) > 0 {
			stop := exec.CommandContext(ctx, "docker", append([]string{"stop"}, containers...)...)
			stop.Stdout, stop.Stderr = os.Stderr, os.Stderr
			if err := stop.Run(); err != nil {
				return fmt.Errorf("stop this stack's unused inference container: %w", err)
			}
		}
	}
	if err := runCompose("dev", composeOpts); err != nil {
		return err
	}
	// The dev stack runs the object store only.
	return removeEnvKey(filepath.Join(p.stack.Root, ".vscode", ".env"), legacyEndpointVar)
}

func (p *stackProvider) ComposeDown(context.Context) error {
	return runCompose("dev", &ComposeOptions{Down: true})
}

// Migrate runs alembic with the stack's explicit database host and port.
func (p *stackProvider) Migrate(ctx context.Context, env []string) error {
	bin, err := alembic.FindAlembicBinary()
	if err != nil {
		return err
	}
	log.Infof("Running migrations against %s:%s", devstack.EnvValue(env, "POSTGRES_HOST"), devstack.EnvValue(env, "POSTGRES_PORT"))
	cmd := exec.CommandContext(ctx, bin, "upgrade", "head")
	cmd.Dir = filepath.Join(p.stack.Root, "backend")
	cmd.Env = env
	var output commandOutputTail
	writer := io.MultiWriter(os.Stderr, &output)
	cmd.Stdout, cmd.Stderr = writer, writer
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("alembic upgrade head: %w\n%s", err, lastLines(string(output.data), 20))
	}
	return nil
}

type commandOutputTail struct {
	data []byte
}

func (b *commandOutputTail) Write(p []byte) (int, error) {
	const limit = 64 * 1024
	n := len(p)
	if n >= limit {
		b.data = append(b.data[:0], p[n-limit:]...)
		return n, nil
	}
	if overflow := len(b.data) + n - limit; overflow > 0 {
		copy(b.data, b.data[overflow:])
		b.data = b.data[:len(b.data)-overflow]
	}
	b.data = append(b.data, p...)
	return n, nil
}

// lastLines returns the last n lines of text.
func lastLines(text string, n int) string {
	lines := strings.Split(strings.TrimRight(text, "\n"), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	return strings.Join(lines, "\n")
}

func (p *stackProvider) Plan(root string, ports map[string]int, env devstack.Env, opts devstack.Options) ([]devstack.Spec, error) {
	launch, err := devstack.LoadLaunch(filepath.Join(root, ".vscode", "launch.json"))
	if err != nil {
		return nil, err
	}
	return devstack.LaunchPlan(root, launch, ports, env, opts)
}

// InfraEnv maps the leased infrastructure ports to the variables the app
// reads, the same way `ods env` does.
func (p *stackProvider) InfraEnv(ports map[string]int) map[string]string {
	values := map[string]string{}
	for _, svc := range docker.InfraServices {
		for _, spec := range svc.Ports {
			port, ok := ports[spec.ComposeVar]
			if !ok || spec.AppVar == "" {
				continue
			}
			values[spec.AppVar] = spec.AppValue(port)
		}
	}
	return values
}
