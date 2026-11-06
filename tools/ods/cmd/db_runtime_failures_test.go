package cmd

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	log "github.com/sirupsen/logrus"
)

func TestDBRuntimeCLIRejectsConflictingNetworkAndProjectTargets(t *testing.T) {
	for _, args := range [][]string{
		{"upgrade"}, {"downgrade", "base"}, {"current"}, {"history"},
		{"drop", "--yes"}, {"dump", "backup.dump"},
		{"restore", "backup.sql", "--yes"}, {"restore", "--fetch-seeded", "--yes"},
	} {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			bin := dbSetup(t)
			dockerCalls := dbFakeBinary(t, bin, "docker", "exit 91")
			awsCalls := dbFakeBinary(t, bin, "aws", "exit 92")
			rootProject = "selected-project"
			t.Setenv("POSTGRES_HOST", "database.example.com")
			input := filepath.Join(t.TempDir(), "backup.sql")
			dbWriteSnapshot(t, input)
			invocation := append([]string(nil), args...)
			if len(args) > 1 && args[1] == "backup.sql" {
				invocation[1] = input
			}
			logger := log.StandardLogger()
			var output bytes.Buffer
			originalOutput, originalExit := logger.Out, logger.ExitFunc
			logger.SetOutput(&output)
			t.Cleanup(func() { logger.SetOutput(originalOutput); logger.ExitFunc = originalExit })
			type commandExit int
			logger.ExitFunc = func(code int) { panic(commandExit(code)) }
			exitCode := 0
			func() {
				defer func() {
					if recovered := recover(); recovered != nil {
						code, ok := recovered.(commandExit)
						if !ok {
							panic(recovered)
						}
						exitCode = int(code)
					}
				}()
				command := NewDBCommand()
				command.SetArgs(invocation)
				if err := command.Execute(); err != nil {
					t.Fatal(err)
				}
			}()
			if exitCode != 1 || !strings.Contains(output.String(), "--project conflicts with explicit POSTGRES_HOST") {
				t.Fatalf("exit=%d, output=%q", exitCode, output.String())
			}
			if len(dockerCalls()) != 0 || len(awsCalls()) != 0 {
				t.Fatal("conflicting targets triggered database tools or a snapshot download")
			}
			if data, err := os.ReadFile(input); err != nil || string(data) != "snapshot" {
				t.Fatalf("rejected command changed the snapshot: %q, %v", data, err)
			}
		})
	}
}

func TestDBRuntimeMigrationRejectsDisappearedOrReassignedOwner(t *testing.T) {
	for _, change := range []string{"disappeared", "reassigned"} {
		t.Run(change, func(t *testing.T) {
			calls := dbFakeAlembic(t, "")
			t.Setenv("POSTGRES_HOST", "localhost")
			t.Setenv("POSTGRES_PORT", "25432")
			rootIsolated = false
			root, err := os.Getwd()
			if err != nil {
				t.Fatal(err)
			}
			owner, err := devstack.Open(root, "original", devstack.Shared)
			if err != nil {
				t.Fatal(err)
			}
			if err := owner.WriteState(&devstack.State{Ports: map[string]int{"POSTGRES_HOST_PORT": 25432}}); err != nil {
				t.Fatal(err)
			}
			dbFakeBinary(t, os.Getenv("PATH"), "docker", "exit 1")
			target, err := resolveDBMigrationTarget()
			if err != nil || !target.Managed {
				t.Fatalf("target=%+v, err=%v", target, err)
			}
			if change == "disappeared" {
				if err := os.Remove(filepath.Join(owner.StateDir, "state.json")); err != nil {
					t.Fatal(err)
				}
			} else {
				owner.Project = "replacement"
				if err := owner.WriteState(&devstack.State{Ports: map[string]int{"POSTGRES_HOST_PORT": 25432}}); err != nil {
					t.Fatal(err)
				}
			}
			release, err := lockDBMigrationTarget(target, true)
			if err == nil {
				release()
				t.Fatal("migration accepted an obsolete database owner")
			}
			if !strings.Contains(err.Error(), "changed ownership after target selection") || len(calls()) != 0 {
				t.Fatalf("stale target error=%v, alembic calls=%v", err, calls())
			}
		})
	}
}
