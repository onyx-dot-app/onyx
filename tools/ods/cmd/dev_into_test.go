package cmd

import (
	"testing"
)

func TestDevInto_opensZshInTheWorkspace(t *testing.T) {
	// Pin what ensureDockerSock and ensureRemoteUser would otherwise detect
	// and set process-wide.
	t.Setenv("DOCKER_SOCK", "/var/run/docker.sock")
	t.Setenv("DEVCONTAINER_REMOTE_USER", "dev")
	root := t.TempDir()
	calls := kubeFakeTools(t, map[string]string{
		"git":          kubeGitScript(t, root, "main"),
		"devcontainer": "exit 0\n",
	})

	kubeExecute(t, newDevIntoCommand())

	kubeAssertCalls(t, kubeCallsTo(calls(), "devcontainer"), [][]string{
		{"exec", "--workspace-folder", root, "zsh"},
	})
}
