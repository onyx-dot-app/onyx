package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"text/tabwriter"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/impersonate"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/kube"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

const defaultNamespace = "onyx"

// impersonateFlags are shared by every impersonate subcommand.
type impersonateFlags struct {
	cluster   string
	region    string
	namespace string
	ctx       string
	host      string
}

// NewImpersonateCommand creates the parent impersonate command.
func NewImpersonateCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "impersonate",
		Short: "Mint, list, and revoke sessions on a single-tenant deployment",
		Long: `Impersonate a user on a single-tenant Kubernetes customer deployment.

Single tenant has no UI impersonation flow, so support access means writing a
session token into Redis. This runs a Python payload inside the customer's
api-server pod, which already holds the Redis and database credentials plus
network reach into the VPC. No AWS console or redis-cli is needed.

Everything you do while impersonating persists as that user. Use the shortest
usable TTL and revoke when you finish.

Select the cluster either directly:

  ods impersonate mint --email admin@customer.com -C gearbox-prod -R us-east-1

or through a KUBE_CTX_* environment variable, as ods whois does:

  export KUBE_CTX_GEARBOX="<cluster> <region> <namespace>"
  ods impersonate list -c gearbox`,
	}

	cmd.AddCommand(NewImpersonateMintCommand())
	cmd.AddCommand(NewImpersonateListCommand())
	cmd.AddCommand(NewImpersonateRevokeCommand())

	return cmd
}

// addImpersonateFlags registers the cluster selection flags on a subcommand.
func addImpersonateFlags(cmd *cobra.Command, f *impersonateFlags) {
	cmd.Flags().StringVarP(&f.cluster, "cluster", "C", "", "EKS cluster name")
	cmd.Flags().StringVarP(&f.region, "region", "R", "", "AWS region (required with --cluster)")
	cmd.Flags().StringVarP(&f.namespace, "namespace", "n", defaultNamespace, "Kubernetes namespace")
	cmd.Flags().StringVarP(&f.ctx, "context", "c", "", "cluster context name (maps to KUBE_CTX_<NAME> env var)")
	cmd.Flags().StringVar(&f.host, "host", "", "customer URL, used in the printed steps")
}

// connect resolves the target cluster and finds a ready api-server pod. The
// resolved cluster is always logged, so the target is never silent.
func (f *impersonateFlags) connect() (*kube.Cluster, string) {
	var c *kube.Cluster
	switch {
	case f.cluster != "" && f.region != "":
		c = &kube.Cluster{Name: f.cluster, Region: f.region, Namespace: f.namespace}
	case f.cluster != "" || f.region != "":
		log.Fatal("--cluster and --region go together")
	case f.ctx != "":
		c = clusterFromEnv(f.ctx)
	default:
		log.Fatal("Select a cluster with --cluster/--region or with --context")
	}

	if err := c.EnsureContext(); err != nil {
		log.Fatalf("Failed to ensure cluster context: %v", err)
	}

	log.Infof("Cluster: %s (%s), namespace %s", c.Name, c.Region, c.Namespace)
	pod, err := c.FindPod(impersonate.APIServerPod)
	if err != nil {
		log.Fatalf("Failed to find api-server pod: %v", err)
	}
	log.Debugf("Using pod: %s", pod)

	return c, pod
}

// operatorEmail identifies who minted a token, for the audit marker.
func operatorEmail() string {
	out, err := exec.Command("git", "config", "user.email").Output()
	if email := strings.TrimSpace(string(out)); err == nil && email != "" {
		return email
	}
	if user := os.Getenv("USER"); user != "" {
		return user
	}
	return "unknown"
}

// NewImpersonateMintCommand creates the impersonate mint subcommand.
func NewImpersonateMintCommand() *cobra.Command {
	var f impersonateFlags
	var ttl time.Duration
	var yes bool

	cmd := &cobra.Command{
		Use:   "mint",
		Short: "Write a session token for a user and print its cookie value",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			email, _ := cmd.Flags().GetString("email")
			c, pod := f.connect()

			if !yes && !prompt.Confirm(fmt.Sprintf("\nMint a session for %s on %s? [Y/n] ", email, c.Name)) {
				log.Info("Aborted.")
				return
			}

			result, err := impersonate.Mint(c, pod, email, int(ttl.Seconds()), operatorEmail())
			if err != nil {
				log.Fatalf("Failed to mint session: %v", err)
			}
			printMintResult(result, f.host)
		},
	}

	addImpersonateFlags(cmd, &f)
	cmd.Flags().String("email", "", "user to impersonate")
	cmd.Flags().DurationVar(&ttl, "ttl", time.Hour, "session lifetime")
	cmd.Flags().BoolVar(&yes, "yes", false, "skip the confirmation prompt")
	_ = cmd.MarkFlagRequired("email")

	return cmd
}

func printMintResult(result *impersonate.Result, host string) {
	if host == "" {
		host = "https://<customer>.onyx.app"
	}
	host = strings.TrimSuffix(host, "/")

	fmt.Printf("\nMinted a session for %s (role: %s)\n", result.Email, result.Role)
	fmt.Printf("  expires at : %s\n", result.ExpiresAt)
	fmt.Println("  cookie     : fastapiusersauth")
	fmt.Printf("  value      : %s\n\n", result.Token)

	fmt.Println("To use it:")
	fmt.Printf("  1. Open %s/api/settings - this avoids the SSO redirect loop.\n", host)
	fmt.Println("  2. In the devtools console, run:")
	fmt.Printf("     document.cookie = %q\n", fmt.Sprintf("fastapiusersauth=%s; path=/", result.Token))
	fmt.Printf("  3. Go to %s/chat\n\n", host)

	fmt.Println("Everything you do persists as this user. Revoke when you finish:")
	fmt.Printf("  ods impersonate revoke --token %s\n\n", result.Token)
}

// NewImpersonateListCommand creates the impersonate list subcommand.
func NewImpersonateListCommand() *cobra.Command {
	var f impersonateFlags

	cmd := &cobra.Command{
		Use:   "list",
		Short: "List every session token on the deployment",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			c, pod := f.connect()

			result, err := impersonate.List(c, pod)
			if err != nil {
				log.Fatalf("Failed to list sessions: %v", err)
			}
			if len(result.Sessions) == 0 {
				fmt.Println("No session tokens found.")
				return
			}

			fmt.Println()
			w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
			_, _ = fmt.Fprintln(w, "EMAIL\tSTATUS\tTTL\tIMPERSONATED BY")
			_, _ = fmt.Fprintln(w, "-----\t------\t---\t---------------")
			for _, s := range result.Sessions {
				ttl := "-"
				if s.TTLSeconds >= 0 {
					ttl = (time.Duration(s.TTLSeconds) * time.Second).String()
				}
				_, _ = fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", s.Email, s.Status, ttl, s.ImpersonatedBy)
			}
			_ = w.Flush()
		},
	}

	addImpersonateFlags(cmd, &f)

	return cmd
}

// NewImpersonateRevokeCommand creates the impersonate revoke subcommand.
func NewImpersonateRevokeCommand() *cobra.Command {
	var f impersonateFlags
	var includeReal bool

	cmd := &cobra.Command{
		Use:   "revoke",
		Short: "Delete a minted session, or every impersonation session for a user",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			email, _ := cmd.Flags().GetString("email")
			token, _ := cmd.Flags().GetString("token")
			if email == "" && token == "" {
				log.Fatal("revoke needs --email or --token")
			}

			c, pod := f.connect()

			result, err := impersonate.Revoke(c, pod, email, token, includeReal)
			if err != nil {
				log.Fatalf("Failed to revoke sessions: %v", err)
			}

			log.Infof("Revoked %d session(s).", result.Deleted)
			if email != "" && result.Deleted == 0 {
				log.Info("No impersonation sessions matched. Pass --include-real-sessions to drop the user's own sessions too.")
			}
		},
	}

	addImpersonateFlags(cmd, &f)
	cmd.Flags().String("email", "", "revoke this user's impersonation sessions")
	cmd.Flags().String("token", "", "revoke this specific token")
	cmd.Flags().BoolVar(&includeReal, "include-real-sessions", false, "also drop the user's own logins")

	return cmd
}
