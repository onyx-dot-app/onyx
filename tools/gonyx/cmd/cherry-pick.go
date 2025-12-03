package cmd

import (
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

// NewListCommand creates a new list command
func NewCherryPickCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "cherry-pick",
		Short: "Cherry-pick a commit to a release branch",
		Run:   runCherryPick,
	}

	return cmd
}

func runCherryPick(cmd *cobra.Command, opts []string) {
	log.Debug("Debug log in runCherryPick")
}
