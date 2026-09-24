package cmd

import (
	"testing"
)

func TestParseTunnelPorts(t *testing.T) {
	cases := []struct {
		spec          string
		wantHost      int
		wantContainer int
		wantErr       string
	}{
		{spec: "8080", wantHost: 8080, wantContainer: 8080},
		{spec: "9000:8080", wantHost: 9000, wantContainer: 8080},
		{spec: "1:65535", wantHost: 1, wantContainer: 65535},
		{spec: "http", wantErr: `not a number: "http"`},
		{spec: "0", wantErr: "out of range: 0"},
		{spec: "65536", wantErr: "out of range: 65536"},
		{spec: "x:8080", wantErr: `host port: not a number: "x"`},
		{spec: "9000:", wantErr: `container port: not a number: ""`},
		{spec: "1:2:3", wantErr: "expected <port> or <host>:<container>"},
	}
	for _, c := range cases {
		t.Run(c.spec, func(t *testing.T) {
			host, container, err := parseTunnelPorts(c.spec)
			if c.wantErr != "" {
				if err == nil || err.Error() != c.wantErr {
					t.Fatalf("expected error %q, got %v", c.wantErr, err)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if host != c.wantHost || container != c.wantContainer {
				t.Fatalf("expected %d:%d, got %d:%d", c.wantHost, c.wantContainer, host, container)
			}
		})
	}
}

func TestDevTunnel_forwardsThroughDockerExecOnLoopback(t *testing.T) {
	root := t.TempDir()
	calls := kubeFakeTools(t, map[string]string{
		"git":    kubeGitScript(t, root, "main"),
		"docker": "printf 'abc123\\n'\n",
		"socat":  "exit 0\n",
	})

	kubeExecute(t, newDevTunnelCommand(), "9000:8080")

	got := calls()
	kubeAssertCalls(t, kubeCallsTo(got, "docker"), [][]string{
		{"ps", "-q", "--filter", "label=devcontainer.local_folder=" + root},
	})
	kubeAssertCalls(t, kubeCallsTo(got, "socat"), [][]string{
		{"TCP-LISTEN:9000,fork,reuseaddr", `SYSTEM:docker exec -i abc123 socat - TCP\:127.0.0.1\:8080`},
	})
}
