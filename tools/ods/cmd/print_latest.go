package cmd

import (
	"fmt"
	"os"

	"github.com/jmelahman/tag/git"
	"github.com/spf13/cobra"
)

// NewLatestStableTagCommand creates the latest-stable-tag command.
func NewLatestStableTagCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "latest-stable-tag",
		Short: "Print the git tag that should receive the 'latest' Docker tag",
		Long: `Print the highest stable (non-pre-release) semver tag in the repository.

This is used during deployment to decide whether a given tag should
receive the "latest" tag on Docker Hub. Only the highest vX.Y.Z tag
qualifies. Tags with pre-release suffixes (e.g. v1.2.3-beta,
v1.2.3-cloud.1) are excluded.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			tag, err := git.GetLatestStableSemverTag("")
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			fmt.Println(tag)
		},
	}

	return cmd
}
