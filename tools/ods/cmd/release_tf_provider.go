package cmd

import (
	"github.com/spf13/cobra"
)

var tfProviderRelease = prefixedTagRelease{
	tagPrefix: "tf-provider/v",
	tagGlob:   "tf-provider/*",
	subject:   "terraform-provider-onyx",
	publishes: "release-terraform-provider.yml will mirror it, and the mirror publishes to the Terraform Registry.",
}

// NewReleaseTFProviderCommand creates the `ods release tf-provider` command.
func NewReleaseTFProviderCommand() *cobra.Command {
	opts := &prefixedTagOptions{}

	cmd := &cobra.Command{
		Use:   "tf-provider",
		Short: "Cut a new terraform-provider-onyx release by pushing a tf-provider/vX.Y.Z tag",
		Long: `Cut a new terraform-provider-onyx release by pushing a tf-provider/vX.Y.Z tag.

The tf-provider/v* tags are the source of truth for the version — nothing in
terraform-provider-onyx/ records it, and the build stamps it from the tag. This
command reads the latest tf-provider/v* tag, computes the next version, and pushes
the new tag to origin.

release-terraform-provider.yml then copies terraform-provider-onyx/ to the release
mirror as one commit tagged vX.Y.Z, and the mirror's own Publish workflow builds,
signs and publishes the release the Terraform Registry ingests.

By default the patch version is bumped. Use --bump minor|major, or pin an exact
--version.

Example usage:

    $ ods release tf-provider
    $ ods release tf-provider --bump minor
    $ ods release tf-provider --version 1.0.0`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			tfProviderRelease.run(opts)
		},
	}

	tfProviderRelease.addFlags(cmd, opts)

	return cmd
}
