package cmd

import (
	"fmt"
	"os"
	"regexp"
	"strings"
	"text/tabwriter"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/kube"
)

var safeIdentifier = regexp.MustCompile(`^[a-zA-Z0-9_\-]+$`)

// NewWhoisCommand creates the whois command for looking up users/tenants.
func NewWhoisCommand() *cobra.Command {
	var ctx string

	cmd := &cobra.Command{
		Use:   "whois <email-fragment or tenant-id>",
		Short: "Look up users and admins by email or tenant ID",
		Long: `Look up tenant and user information from the data plane PostgreSQL database.

Requires: AWS SSO login, kubectl access to the EKS cluster.

Two modes (auto-detected):

  Email fragment:
    ods whois chris
    → Searches user_tenant_mapping for emails matching '%chris%'

  Tenant ID:
    ods whois tenant_abcd1234-...
    → Lists all admin emails in that tenant

Cluster connection is configured via KUBE_CTX_* environment variables.
Each variable is a space-separated tuple: "cluster region namespace"

  export KUBE_CTX_DATA_PLANE="<cluster> <region> <namespace>"
  export KUBE_CTX_CONTROL_PLANE="<cluster> <region> <namespace>"
  etc...

Use -c to select which context (default: data_plane).`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runWhois(args[0], ctx)
		},
	}

	cmd.Flags().StringVarP(&ctx, "context", "c", "data_plane", "cluster context name (maps to KUBE_CTX_<NAME> env var)")

	return cmd
}

func clusterFromEnv(name string) *kube.Cluster {
	envKey := "KUBE_CTX_" + strings.ToUpper(name)
	val := os.Getenv(envKey)
	if val == "" {
		log.Fatalf("Environment variable %s is not set.\n\nSet it as a space-separated tuple:\n  export %s=\"<cluster> <region> <namespace>\"", envKey, envKey)
	}

	parts := strings.Fields(val)
	if len(parts) != 3 {
		log.Fatalf("%s must be a space-separated tuple of 3 values (cluster region namespace), got: %q", envKey, val)
	}

	return &kube.Cluster{Name: parts[0], Region: parts[1], Namespace: parts[2]}
}

// queryPod runs a SQL query via pginto on the given pod and returns cleaned output lines.
func queryPod(c *kube.Cluster, pod, sql string) []string {
	raw, err := c.ExecOnPod(pod, "pginto", "-A", "-t", "-F", "\t", "-c", sql)
	if err != nil {
		log.Fatalf("Query failed: %v", err)
	}

	var lines []string
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		line = strings.TrimSpace(line)
		if line != "" && !strings.HasPrefix(line, "Connecting to ") {
			lines = append(lines, line)
		}
	}
	return lines
}

func runWhois(query string, ctx string) {
	c := clusterFromEnv(ctx)

	if err := c.EnsureContext(); err != nil {
		log.Fatalf("Failed to ensure cluster context: %v", err)
	}

	log.Info("Finding api-server pod...")
	pod, err := c.FindPod("api-server")
	if err != nil {
		log.Fatalf("Failed to find api-server pod: %v", err)
	}
	log.Debugf("Using pod: %s", pod)

	if strings.HasPrefix(query, "tenant_") {
		findAdminsByTenant(c, pod, query)
	} else {
		findByEmail(c, pod, query)
	}
}

func findByEmail(c *kube.Cluster, pod, fragment string) {
	fragment = strings.NewReplacer("'", "", `"`, "", `;`, "", `\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(fragment)

	sql := fmt.Sprintf(
		`SELECT email, tenant_id, active FROM public.user_tenant_mapping WHERE email LIKE '%%%s%%' ORDER BY email;`,
		fragment,
	)

	log.Infof("Searching for emails matching '%%%s%%'...", fragment)
	lines := queryPod(c, pod, sql)
	if len(lines) == 0 {
		fmt.Println("No results found.")
		return
	}

	fmt.Println()
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	_, _ = fmt.Fprintln(w, "EMAIL\tTENANT ID\tACTIVE")
	_, _ = fmt.Fprintln(w, "-----\t---------\t------")
	for _, line := range lines {
		_, _ = fmt.Fprintln(w, line)
	}
	_ = w.Flush()
}

func findAdminsByTenant(c *kube.Cluster, pod, tenantID string) {
	if !safeIdentifier.MatchString(tenantID) {
		log.Fatalf("Invalid tenant ID: %q (must be alphanumeric, hyphens, underscores only)", tenantID)
	}

	sql := fmt.Sprintf(
		`SELECT email FROM "%s"."user" WHERE role = 'ADMIN' AND is_active = true AND email NOT LIKE 'api_key__%%' ORDER BY email;`,
		tenantID,
	)

	log.Infof("Fetching admin emails for %s...", tenantID)
	lines := queryPod(c, pod, sql)
	if len(lines) == 0 {
		fmt.Println("No admin users found for this tenant.")
		return
	}

	fmt.Println()
	fmt.Println("EMAIL")
	fmt.Println("-----")
	for _, line := range lines {
		fmt.Println(line)
	}
}
