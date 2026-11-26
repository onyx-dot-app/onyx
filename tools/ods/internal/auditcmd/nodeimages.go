package auditcmd

import (
	"encoding/json"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
	"github.com/spf13/cobra"
)

// The nightly sync owns suppression and issue state. Blockers are data here.
func newNodeImagesCommand() *cobra.Command {
	return &cobra.Command{
		Use: "node-images <web-runtime-image>", Args: cobra.ExactArgs(1),
		Short: "Collect a nightly audit report for pinned Node images",
		RunE: func(cmd *cobra.Command, args []string) error {
			result, err := audit.ScanNodeImages(args[0])
			if err != nil {
				return err
			}
			return json.NewEncoder(cmd.OutOrStdout()).Encode(result)
		},
	}
}
