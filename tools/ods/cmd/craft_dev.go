package cmd

import (
	"fmt"
	"os/exec"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/childproc"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// The Python launchers hold the craft-dev logic; these commands only build
// their argv. Unset flags are not forwarded, so the launchers keep their own
// defaults and read CRAFT_DEV_PROFILE, CRAFT_DEV_CONTEXT and CRAFT_DEV_USER.
const (
	craftDevTarget   = "craft-dev"
	craftDevLauncher = "deployment/helm/dev/launch.py"
	craftDevDoctor   = "deployment/helm/dev/dev.py"
	craftDevVM       = "deployment/helm/dev/craft_fc_vm.py"
)

type craftDevOptions struct {
	profile string
	context string
	port    int
	user    string
	tenant  string
	verbose bool
}

// NewCraftDevCommand creates the "craft-dev" command group for a local API and
// web server against a shared remote Firecracker dev cluster.
func NewCraftDevCommand() *cobra.Command {
	opts := &craftDevOptions{}
	cmd := &cobra.Command{
		Use:   "craft-dev",
		Short: "Run Craft locally against the shared Firecracker dev cluster",
		Long: `Run Craft locally against the shared Firecracker dev cluster.

The cluster comes from a profile file: --profile, else $CRAFT_DEV_PROFILE,
else dev/craft-dev.yaml in the onyx-internal checkout next to this repo.
kubectl always gets the context explicitly; --context (or $CRAFT_DEV_CONTEXT)
must be one that the profile allows.

The commands run the Python launchers in deployment/helm/dev with uv.

Examples:
  ods craft-dev doctor
  ods craft-dev api
  ods craft-dev web
  ods craft-dev skills push ./my-skills --wake
  ods craft-dev exec -- ls -la /workspace`,
	}
	cmd.PersistentFlags().StringVar(&opts.profile, "profile", "", "Profile file (default: $CRAFT_DEV_PROFILE, else onyx-internal)")
	cmd.PersistentFlags().StringVar(&opts.context, "context", "", "Kube context the profile allows (default: $CRAFT_DEV_CONTEXT, else the profile's)")

	cmd.AddCommand(newCraftDevDoctorCommand(opts))
	cmd.AddCommand(newCraftDevAPICommand(opts))
	cmd.AddCommand(newCraftDevWebCommand(opts))
	cmd.AddCommand(newCraftDevSkillsCommand(opts))
	cmd.AddCommand(newCraftDevVMCommand(opts, &cobra.Command{
		Use:   "vms",
		Short: "Show your VM",
		Args:  cobra.NoArgs,
	}, nil))
	cmd.AddCommand(newCraftDevVMCommand(opts, &cobra.Command{
		Use:   "exec [flags] -- <command> [args...]",
		Short: "Run a command in your VM as the sandbox user",
		Args:  cobra.MinimumNArgs(1),
	}, func(f *pflag.FlagSet) {
		f.Bool("wake", false, "Start the VM if it is stopped")
		f.String("cwd", "", "Working directory in the VM (default /)")
	}))
	cmd.AddCommand(newCraftDevVMCommand(opts, &cobra.Command{
		Use:   "logs",
		Short: "Show guest and agent log lines of your VM",
		Args:  cobra.NoArgs,
	}, func(f *pflag.FlagSet) {
		f.Bool("guest", false, "Only guest console lines")
		f.Bool("agent", false, "Only agent lines")
		f.String("since", "", "Lines newer than this duration (default 1h)")
		f.Int("tail", 0, "Number of lines to show")
		f.BoolP("follow", "f", false, "Follow new lines")
	}))
	cmd.AddCommand(newCraftDevVMCommand(opts, &cobra.Command{
		Use:   "reset",
		Short: "Save your sessions, then stop your VM",
		Args:  cobra.NoArgs,
	}, func(f *pflag.FlagSet) {
		f.Bool("force", false, "Stop without a save")
	}))

	return cmd
}

func newCraftDevDoctorCommand(opts *craftDevOptions) *cobra.Command {
	return &cobra.Command{
		Use:   "doctor",
		Short: "Check AWS, VPN egress, kube, Telepresence, host agents and the Alembic head (read-only)",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runCraftDev(craftDevArgv(craftDevDoctor, opts.targetArgs(), "doctor"))
		},
	}
}

func newCraftDevAPICommand(opts *craftDevOptions) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "api [-- uvicorn args...]",
		Short: "Start the local API server against the cluster (needs Telepresence)",
		Run: func(cmd *cobra.Command, args []string) {
			runCraftDev(craftDevArgv(craftDevLauncher, opts.launcherArgs(), "api", withSeparator(args)...))
		},
	}
	cmd.Flags().IntVar(&opts.port, "port", 0, "Local API port (default: $CRAFT_API_PORT, else 8080 or the next free port)")
	return cmd
}

func newCraftDevWebCommand(opts *craftDevOptions) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "web",
		Short: "Start the local web server that proxies to the local API",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runCraftDev(craftDevArgv(craftDevLauncher, opts.launcherArgs(), "web"))
		},
	}
	cmd.Flags().IntVar(&opts.port, "port", 0, "Port of the local API (default: $CRAFT_API_PORT, else 8080)")
	return cmd
}

func newCraftDevSkillsCommand(opts *craftDevOptions) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "skills",
		Short: "Managed drive commands for your VM",
	}
	cmd.AddCommand(newCraftDevVMCommand(opts, &cobra.Command{
		Use:   "push <dir>",
		Short: "Put a local directory on a managed mount of your VM",
		Args:  cobra.ExactArgs(1),
	}, func(f *pflag.FlagSet) {
		f.String("mount", "", "Managed mount: skills, user-uploads or spaces (default skills)")
		f.Bool("wake", false, "Start the VM if it is stopped")
	}))
	return cmd
}

// newCraftDevVMCommand completes a craft_fc_vm.py subcommand. The command path
// below "craft-dev" becomes the launcher subcommand, and set local flags are
// forwarded by name.
func newCraftDevVMCommand(opts *craftDevOptions, cmd *cobra.Command, flags func(*pflag.FlagSet)) *cobra.Command {
	if flags != nil {
		flags(cmd.Flags())
	}
	cmd.Flags().StringVar(&opts.user, "user", "", "Your Onyx login email (default: $CRAFT_DEV_USER, else the profile's)")
	cmd.Flags().StringVar(&opts.tenant, "tenant", "", "Tenant ID (default: looked up from the email)")
	cmd.Flags().BoolVar(&opts.verbose, "verbose", false, "Show the pod helper output")
	cmd.Run = func(c *cobra.Command, args []string) {
		runCraftDev(craftDevArgv(craftDevVM, opts.vmArgs(), craftDevSubcommand(c), craftDevVMRest(c, args)...))
	}
	return cmd
}

func (o *craftDevOptions) targetArgs() []string {
	args := []string{"--target", craftDevTarget}
	if o.profile != "" {
		args = append(args, "--profile", o.profile)
	}
	if o.context != "" {
		args = append(args, "--context", o.context)
	}
	return args
}

func (o *craftDevOptions) launcherArgs() []string {
	args := o.targetArgs()
	if o.port != 0 {
		args = append(args, "--port", strconv.Itoa(o.port))
	}
	return args
}

func (o *craftDevOptions) vmArgs() []string {
	var args []string
	if o.profile != "" {
		args = append(args, "--profile", o.profile)
	}
	if o.context != "" {
		args = append(args, "--context", o.context)
	}
	if o.user != "" {
		args = append(args, "--user", o.user)
	}
	if o.tenant != "" {
		args = append(args, "--tenant", o.tenant)
	}
	if o.verbose {
		args = append(args, "--verbose")
	}
	return args
}

// craftDevSubcommand returns the words between "craft-dev" and the flags, for
// example "skills push".
func craftDevSubcommand(c *cobra.Command) string {
	name := c.Name()
	for p := c.Parent(); p != nil && p.Name() != craftDevTarget; p = p.Parent() {
		name = p.Name() + " " + name
	}
	return name
}

var craftDevGlobalFlags = map[string]bool{"user": true, "tenant": true, "verbose": true}

// craftDevVMRest forwards the set subcommand flags, then the positional
// arguments. exec keeps its "--" so the command reaches the VM unchanged.
func craftDevVMRest(c *cobra.Command, args []string) []string {
	var rest []string
	c.LocalNonPersistentFlags().VisitAll(func(f *pflag.Flag) {
		if !f.Changed || craftDevGlobalFlags[f.Name] {
			return
		}
		if f.Value.Type() == "bool" {
			rest = append(rest, "--"+f.Name)
		} else {
			rest = append(rest, fmt.Sprintf("--%s=%s", f.Name, f.Value.String()))
		}
	})
	if c.Name() == "exec" {
		return append(append(rest, "--"), args...)
	}
	return append(rest, args...)
}

func withSeparator(args []string) []string {
	if len(args) == 0 {
		return nil
	}
	return append([]string{"--"}, args...)
}

// craftDevArgv builds the uv argv: global launcher flags go before the
// subcommand, as argparse needs.
func craftDevArgv(script string, global []string, subcommand string, rest ...string) []string {
	argv := []string{"run", "--frozen", "python", script}
	argv = append(argv, global...)
	argv = append(argv, strings.Fields(subcommand)...)
	return append(argv, rest...)
}

func runCraftDev(argv []string) {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	log.Debugf("Running in %s: uv %v", root, argv)
	c := exec.Command("uv", argv...)
	c.Dir = root
	childproc.Run(c, "uv")
}
