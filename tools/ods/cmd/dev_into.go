package cmd

import (
	"os"
	"os/exec"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

func newDevIntoCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "into",
		Short: "Open a shell inside the running devcontainer",
		Long: `Open an interactive zsh shell inside the running devcontainer.

Examples:
  ods dev into`,
		Run: func(cmd *cobra.Command, args []string) {
			runDevExec([]string{"zsh"})
		},
	}

	return cmd
}

// runDevExec executes "devcontainer exec --workspace-folder <root> <command...>".
func runDevExec(command []string) {
	checkDevcontainerCLI()
	ensureDockerSock()
	ensureRemoteUser()

	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	args := []string{"exec", "--workspace-folder", root}
	args = append(args, command...)

	log.Debugf("Running: devcontainer %v", args)

	c := exec.Command("devcontainer", args...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Stdin = os.Stdin

	if err := c.Run(); err != nil {
		log.Fatalf("devcontainer exec failed: %v", err)
	}
}
