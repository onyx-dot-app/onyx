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

var tenantIDPattern = regexp.MustCompile(`^tenant_.+$`)

// NewWhoisCommand creates the find command for looking up users/tenants.
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

func parseKubeCtx(name string) (cluster, region, namespace string) {
	envKey := "KUBE_CTX_" + strings.ToUpper(name)
	val := os.Getenv(envKey)
	if val == "" {
		log.Fatalf("Environment variable %s is not set.\n\nSet it as a space-separated tuple:\n  export %s=\"<cluster> <region> <namespace>\"", envKey, envKey)
	}

	parts := strings.Fields(val)
	if len(parts) != 3 {
		log.Fatalf("%s must be a space-separated tuple of 3 values (cluster region namespace), got: %q", envKey, val)
	}

	return parts[0], parts[1], parts[2]
}

func runWhois(query string, ctx string) {
	cluster, region, namespace := parseKubeCtx(ctx)

	// 1. Switch to cluster context
	log.Infof("Switching to %s context...", ctx)
	if err := kube.UseCluster(cluster, region, namespace); err != nil {
		log.Fatalf("Failed to switch context: %v", err)
	}

	// 2. Find api-server pod
	log.Info("Finding api-server pod...")
	pod, err := kube.FindPod("api-server")
	if err != nil {
		log.Fatalf("Failed to find api-server pod: %v", err)
	}
	log.Debugf("Using pod: %s", pod)

	// 3. Detect mode and run query
	if tenantIDPattern.MatchString(query) {
		findAdminsByTenant(pod, query)
	} else {
		findByEmail(pod, query)
	}
}

func findByEmail(pod, fragment string) {
	// Sanitize: strip any single quotes to prevent injection
	fragment = strings.ReplaceAll(fragment, "'", "")

	sql := fmt.Sprintf(
		`SELECT email, tenant_id, active FROM public.user_tenant_mapping WHERE email LIKE '%%%s%%' ORDER BY email;`,
		fragment,
	)

	log.Infof("Searching for emails matching '%%%s%%'...", fragment)
	raw, err := kube.ExecOnPod(pod, "pginto", "-A", "-t", "-F", "\t", "-c", sql)
	if err != nil {
		log.Fatalf("Query failed: %v", err)
	}

	output := strings.TrimSpace(raw)
	if output == "" {
		fmt.Println("No results found.")
		return
	}

	// Pretty print as table
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	_, _ = fmt.Fprintln(w, "EMAIL\tTENANT ID\tACTIVE")
	_, _ = fmt.Fprintln(w, "-----\t---------\t------")
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		_, _ = fmt.Fprintln(w, line)
	}
	_ = w.Flush()
}

func findAdminsByTenant(pod, tenantID string) {
	// Sanitize
	tenantID = strings.ReplaceAll(tenantID, "'", "")
	tenantID = strings.ReplaceAll(tenantID, `"`, "")

	sql := fmt.Sprintf(
		`SELECT email FROM "%s"."user" WHERE role = 'ADMIN' AND is_active = true ORDER BY email;`,
		tenantID,
	)

	log.Infof("Fetching admin emails for %s...", tenantID)
	raw, err := kube.ExecOnPod(pod, "pginto", "-A", "-t", "-F", "\t", "-c", sql)
	if err != nil {
		log.Fatalf("Query failed: %v", err)
	}

	output := strings.TrimSpace(raw)
	if output == "" {
		fmt.Println("No admin users found for this tenant.")
		return
	}

	fmt.Println("EMAIL")
	fmt.Println("-----")
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			fmt.Println(line)
		}
	}
}
