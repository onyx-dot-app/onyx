package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/release"
)

// NewReleaseClassifyCommand creates the `ods release classify` command.
func NewReleaseClassifyCommand() *cobra.Command {
	var ref string
	var sha string
	var event string

	cmd := &cobra.Command{
		Use:   "classify",
		Short: "Print the build routing for a release tag as GITHUB_OUTPUT lines",
		Long: `Print which images a release tag must build, as GITHUB_OUTPUT key=value lines.

deployment.yml pipes this into $GITHUB_OUTPUT and gates its build jobs on the
result. The keys are:

  build-desktop, build-web, build-web-cloud, build-backend, build-model-server
  is-cloud-tag, is-beta, is-beta-standalone, is-stable, is-latest, is-test-run
  sanitized-tag, short-sha

A cloud tag builds the cloud web image; every other tag builds the standard web
image, plus the desktop app when the tag is a version that is not a beta. The
backend and model server build for every tag. Only the highest stable tag
(vX.Y.Z exactly) in the repository is "latest", so the repository must hold all
tags: fetch them before running this.

Example usage:

    $ ods release classify --ref v4.7.2
    $ ods release classify --ref v4.8.0-beta.1 --sha "$GITHUB_SHA"
    $ ods release classify --ref my-branch --event workflow_dispatch`,
		Args:         cobra.NoArgs,
		SilenceUsage: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			if sha == "" {
				resolved, err := git.ResolveCommit("HEAD")
				if err != nil {
					return err
				}
				sha = resolved
			}
			classification, err := release.Classify(ref, sha, event)
			if err != nil {
				return err
			}
			_, err = fmt.Fprint(os.Stdout, classification.GitHubOutput())
			return err
		},
	}

	cmd.Flags().StringVar(&ref, "ref", "", "Tag name to classify (required)")
	cmd.Flags().StringVar(&sha, "sha", "", "Commit the tag points at (default: HEAD)")
	cmd.Flags().StringVar(&event, "event", "push", "Triggering GitHub event, e.g. push or workflow_dispatch")
	if err := cmd.MarkFlagRequired("ref"); err != nil {
		panic(err)
	}

	return cmd
}
