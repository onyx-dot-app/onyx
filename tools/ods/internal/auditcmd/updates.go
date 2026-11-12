package auditcmd

import (
	"encoding/json"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
	"github.com/spf13/cobra"
	"os"
	"time"
)

func newAuditUpdatesCommand() *cobra.Command {
	var state, name, version, minimum string
	var observe, monitor bool
	cmd := &cobra.Command{Use: "updates", Short: "Observe dependency releases or check their update deadlines", Args: cobra.NoArgs}
	cmd.RunE = func(cmd *cobra.Command, args []string) error {
		policy, err := audit.ReadUpdatePolicy(state)
		// Only a missing local file bootstraps; storage errors never reset deadlines.
		if observe && os.IsNotExist(err) {
			policy = audit.UpdatePolicy{}
		} else if err != nil {
			return err
		}
		if observe {
			updated, err := audit.ObserveUpdate(policy[name], version, minimum, time.Now().UTC())
			if err != nil {
				return err
			}
			policy[name] = updated
			data, err := json.MarshalIndent(policy, "", "  ")
			if err != nil {
				return err
			}
			// Storage upload belongs to the serialized maintenance workflow.
			return os.WriteFile(state, append(data, '\n'), 0600)
		}
		entry, ok := policy[name]
		if !ok {
			return failf("No update policy for %s", name)
		}
		status, err := audit.CheckUpdate(name, version, entry, time.Now().UTC())
		if err != nil {
			return err
		}
		if err := json.NewEncoder(cmd.OutOrStdout()).Encode(status); err != nil {
			return err
		}
		if status.Blocking || (monitor && status.Warning) {
			return failf("%s: %s", name, status.Message)
		}
		return nil
	}
	cmd.Flags().StringVar(&state, "state", audit.DefaultUpdatePolicyURL, "Shared update policy, or local file for observation")
	cmd.Flags().StringVar(&name, "package", "", "Package name in the policy")
	cmd.Flags().StringVar(&version, "version", "", "Installed or observed version")
	cmd.Flags().StringVar(&minimum, "minimum", "", "Emergency minimum (observation only; cannot decrease)")
	cmd.Flags().BoolVar(&observe, "observe", false, "Record a release in a local policy file")
	cmd.Flags().BoolVar(&monitor, "monitor", false, "Fail for updates pending 24 hours or stale observations")
	_ = cmd.MarkFlagRequired("package")
	_ = cmd.MarkFlagRequired("version")
	return cmd
}
