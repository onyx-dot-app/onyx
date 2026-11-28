package execs

import (
	"os"
	"strings"
	"syscall"
	"testing"
)

// TestCredentialRunsAsUser needs root: the daemon is root, its commands are not.
func TestCredentialRunsAsUser(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("needs root")
	}
	for name, isolator := range map[string]func(*testing.T) Isolator{
		"process groups": func(*testing.T) Isolator { return ProcessGroups{} },
		"cgroups":        func(t *testing.T) Isolator { return newTestCgroups(t) },
	} {
		t.Run(name, func(t *testing.T) {
			m, err := NewManager(Config{Isolator: isolator(t), Credential: &syscall.Credential{Uid: 1000, Gid: 1000}})
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(m.Shutdown)
			e, err := m.Start(Spec{Argv: []string{"sh", "-c", "id -u; id -g; id -G"}, Env: []string{"PATH=/usr/bin:/bin"}})
			if err != nil {
				t.Fatal(err)
			}
			<-e.Done()
			out, _, _ := e.Read(Stdout, 0, 4096)
			// Root's supplementary groups are dropped.
			if got := strings.Join(strings.Fields(string(out)), " "); got != "1000 1000 1000" {
				t.Fatalf("id output %q, want uid 1000, gid 1000, groups 1000", out)
			}
		})
	}
}
