package cmd

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

const craftFCSmokeScript = "backend/scripts/craft_fc_smoke.py"

type craftFCSmokeOptions struct {
	context       string
	namespace     string
	selector      string
	container     string
	tenantID      string
	egressURL     string
	skipEgress    bool
	cleanupLeaked bool
	verbose       bool
}

// NewCraftFCCommand creates the "craft-fc" command group for Craft on
// Firecracker installations.
func NewCraftFCCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "craft-fc",
		Short: "Operator commands for Craft on Firecracker",
	}
	cmd.AddCommand(newCraftFCSmokeCommand())
	return cmd
}

func newCraftFCSmokeCommand() *cobra.Command {
	opts := &craftFCSmokeOptions{}
	cmd := &cobra.Command{
		Use:   "smoke --context <ctx>",
		Short: "Run the end-to-end Firecracker smoke test in an api-server pod",
		Long: `Run the end-to-end Firecracker smoke test in an api-server pod.

The command sends backend/scripts/craft_fc_smoke.py from this checkout to a
running api-server pod and runs it there. The script makes a test user and
sandbox, then checks create, exec as uid 1000, a file write and read
(SHA-256), egress through the sandbox proxy, save and stop, resume with the
files intact, and a session purge. It always removes the test user and
sandbox at the end.

The exit code is 0 when every step passes and 1 when a step fails.

Examples:
  ods craft-fc smoke --context my-cluster
  ods craft-fc smoke --context my-cluster --namespace onyx --skip-egress
  ods craft-fc smoke --context my-cluster --cleanup-leaked`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			root, err := paths.GitRoot()
			if err != nil {
				return fmt.Errorf("find git root: %w", err)
			}
			code, err := runCraftFCSmoke(opts, root, cmd.OutOrStdout(), cmd.ErrOrStderr())
			if err != nil {
				return err
			}
			if code != 0 {
				os.Exit(code)
			}
			return nil
		},
	}
	f := cmd.Flags()
	f.StringVar(&opts.context, "context", "", "Kube context of the cluster (required)")
	f.StringVarP(&opts.namespace, "namespace", "n", "onyx", "Namespace of the Onyx release")
	f.StringVar(&opts.selector, "selector", "app=api-server", "Label selector of the api-server pods")
	f.StringVar(&opts.container, "container", "api-server", "Container in the api-server pod")
	f.StringVar(&opts.tenantID, "tenant-id", "", "Tenant ID (required on multi-tenant deployments)")
	f.StringVar(&opts.egressURL, "egress-url", "", "HTTPS URL that the VM must reach (default https://pypi.org/simple/)")
	f.BoolVar(&opts.skipEgress, "skip-egress", false, "Do not check egress, for example on an air-gapped cluster")
	f.BoolVar(&opts.cleanupLeaked, "cleanup-leaked", false, "Only remove test users and sandboxes that an interrupted run left")
	f.BoolVar(&opts.verbose, "verbose", false, "Show the server INFO log lines")
	_ = cmd.MarkFlagRequired("context")
	return cmd
}

// scriptArgs are the flags for craft_fc_smoke.py; unset flags keep its defaults.
func (o *craftFCSmokeOptions) scriptArgs() []string {
	var args []string
	if o.tenantID != "" {
		args = append(args, "--tenant-id", o.tenantID)
	}
	if o.egressURL != "" {
		args = append(args, "--egress-url", o.egressURL)
	}
	if o.skipEgress {
		args = append(args, "--skip-egress")
	}
	if o.cleanupLeaked {
		args = append(args, "--cleanup-leaked")
	}
	if o.verbose {
		args = append(args, "--verbose")
	}
	return args
}

func (o *craftFCSmokeOptions) kubectl(args ...string) []string {
	return append([]string{"--context", o.context, "--namespace", o.namespace}, args...)
}

// runCraftFCSmoke returns the exit code of the script. An error means the
// script did not run.
func runCraftFCSmoke(o *craftFCSmokeOptions, root string, stdout, stderr io.Writer) (int, error) {
	if strings.TrimSpace(o.context) == "" {
		return 0, errors.New("--context is required")
	}
	if o.skipEgress && o.egressURL != "" {
		return 0, errors.New("--skip-egress and --egress-url cannot be used together")
	}
	script, err := os.ReadFile(filepath.Join(root, craftFCSmokeScript))
	if err != nil {
		return 0, fmt.Errorf("read the smoke script: %w", err)
	}
	pod, err := craftFCAPIPod(o)
	if err != nil {
		return 0, err
	}
	log.Infof("Running the smoke test in pod %s/%s (context %s)", o.namespace, pod, o.context)

	// The script reaches python on stdin, so the pod needs no writable path.
	argv := o.kubectl("exec", "-i", pod, "-c", o.container, "--", "python", "-")
	argv = append(argv, o.scriptArgs()...)
	c := exec.Command("kubectl", argv...)
	c.Stdin = bytes.NewReader(script)
	c.Stdout = stdout
	c.Stderr = stderr
	if err := c.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) && exitErr.ExitCode() > 0 {
			return exitErr.ExitCode(), nil
		}
		return 0, fmt.Errorf("kubectl exec: %w", err)
	}
	return 0, nil
}

// craftFCAPIPodTemplate lists the pods that are not terminating and whose
// container is ready: an exec in a terminating pod ends with the pod.
func craftFCAPIPodTemplate(container string) string {
	return `{{range .items}}{{if not .metadata.deletionTimestamp}}{{$pod := .metadata.name}}` +
		`{{range .status.containerStatuses}}{{if and (eq .name ` + strconv.Quote(container) + `) .ready}}` +
		`{{$pod}}{{"\n"}}{{end}}{{end}}{{end}}{{end}}`
}

// craftFCAPIPod returns a running api-server pod with a ready container.
func craftFCAPIPod(o *craftFCSmokeOptions) (string, error) {
	tmpl := craftFCAPIPodTemplate(o.container)
	c := exec.Command("kubectl", o.kubectl(
		"get", "pods", "-l", o.selector,
		"--field-selector", "status.phase=Running",
		"-o", "go-template="+tmpl,
	)...)
	var stderr bytes.Buffer
	c.Stderr = &stderr
	out, err := c.Output()
	if err != nil {
		return "", fmt.Errorf("kubectl get pods: %w: %s", err, strings.TrimSpace(stderr.String()))
	}
	if names := strings.Fields(string(out)); len(names) > 0 {
		return names[0], nil
	}
	return "", fmt.Errorf("no running pod with a ready %s container matches %q in namespace %s", o.container, o.selector, o.namespace)
}
