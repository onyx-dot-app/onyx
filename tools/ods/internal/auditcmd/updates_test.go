package auditcmd

import (
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

func TestEmergencyMinimumDoesNotObserveARelease(t *testing.T) {
	path := filepath.Join(t.TempDir(), "updates.json")
	original := `{"example":{"checked_at":"2026-01-01T00:00:00Z","minimum":"1.0","releases":{"1.1":"2026-01-01T00:00:00Z"}}}`
	if err := os.WriteFile(path, []byte(original), 0600); err != nil {
		t.Fatal(err)
	}
	before, err := audit.ReadUpdatePolicy(path)
	if err != nil {
		t.Fatal(err)
	}
	cmd := newAuditUpdatesCommand()
	cmd.SetOut(io.Discard)
	cmd.SetArgs([]string{"--state", path, "--package", "example", "--minimum", "1.2"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	after, err := audit.ReadUpdatePolicy(path)
	if err != nil {
		t.Fatal(err)
	}
	entry := after["example"]
	if entry.Minimum != "1.2" || !entry.CheckedAt.Equal(before["example"].CheckedAt) || !reflect.DeepEqual(entry.Releases, before["example"].Releases) {
		t.Fatalf("changed observation history: %+v", entry)
	}
	status, err := audit.CheckUpdate("example", "1.1", entry, time.Now())
	if err != nil || !status.Blocking {
		t.Fatalf("minimum not enforced: %+v %v", status, err)
	}
	for _, args := range [][]string{
		{"--minimum", "1.0"}, {"--minimum", "invalid"}, {"--minimum", "1.3", "--version", "1.3"}, {"--minimum", "1.3", "--monitor"},
	} {
		cmd := newAuditUpdatesCommand()
		cmd.SetOut(io.Discard)
		cmd.SetErr(io.Discard)
		cmd.SetArgs(append([]string{"--state", path, "--package", "example"}, args...))
		if err := cmd.Execute(); err == nil {
			t.Fatalf("accepted %v", args)
		}
	}
}

func TestUpdatesCommandModesAndFailures(t *testing.T) {
	for _, tc := range []struct {
		name, state string
		args        []string
		fail        bool
	}{
		{"bootstrap", "", []string{"--observe", "--version", "1.1", "--minimum", "1.0"}, false},
		{"read missing", "", []string{"--version", "1.1"}, true},
		{"minimum cannot bootstrap", "", []string{"--minimum", "1.1"}, true},
		{"invalid observation", "", []string{"--observe", "--version", "bad"}, true},
		{"invalid state", "no json", []string{"--observe", "--version", "1"}, true},
		{"missing package", `{"other":{}}`, []string{"--version", "1"}, true},
		{"minimum missing package", `{"other":{}}`, []string{"--minimum", "1"}, true},
		{"minimum invalid history", `{"example":{}}`, []string{"--minimum", "1"}, true},
		{"invalid history", `{"example":{}}`, []string{"--version", "1"}, true},
		{"no mode", "", nil, true},
		{"mixed modes", "", []string{"--observe", "--monitor", "--version", "1"}, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "updates.json")
			if tc.state != "" {
				if err := os.WriteFile(path, []byte(tc.state), 0600); err != nil {
					t.Fatal(err)
				}
			}
			cmd := newAuditUpdatesCommand()
			cmd.SetOut(io.Discard)
			cmd.SetErr(io.Discard)
			cmd.SetArgs(append([]string{"--state", path, "--package", "example"}, tc.args...))
			if err := cmd.Execute(); (err != nil) != tc.fail {
				t.Fatalf("error=%v fail=%v", err, tc.fail)
			}
		})
	}
}

func TestUpdatesCommandChecksAndReports(t *testing.T) {
	path := filepath.Join(t.TempDir(), "updates.json")
	cmd := newAuditUpdatesCommand()
	cmd.SetOut(io.Discard)
	cmd.SetArgs([]string{"--state", path, "--package", "example", "--observe", "--version", "2", "--minimum", "1"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	for _, version := range []string{"0", "1", "2"} {
		cmd := newAuditUpdatesCommand()
		cmd.SetOut(io.Discard)
		cmd.SetErr(io.Discard)
		cmd.SetArgs([]string{"--state", path, "--package", "example", "--version", version, "--monitor"})
		if err := cmd.Execute(); (err != nil) != (version == "0") {
			t.Fatalf("version %s: %v", version, err)
		}
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = file.Close() }()
	cmd = newAuditUpdatesCommand()
	cmd.SetOut(file)
	cmd.SetErr(io.Discard)
	cmd.SetArgs([]string{"--state", path, "--package", "example", "--version", "2"})
	if err := cmd.Execute(); err == nil {
		t.Fatal("failed report write passed")
	}
}

func TestImageUpdateDeadlineUsesSharedCommand(t *testing.T) {
	bin := fakeBinDir(t)
	sbom := writeFixture(t, t.TempDir(), "inventory.json", `{"components":[{"type":"application","name":"example","version":"1","cpe":"cpe:2.3:a:vendor:example:1:*:*:*:*:*:*:*"}]}`)
	writeFakeCommand(t, bin, "docker", `case "$1" in
 create) echo fixture;;
 cp) cp "`+sbom+`" "$3";;
 run) echo '{"matches":[]}' ;;
 rm) ;;
 *) exit 99;;
 esac`)
	policy := writeFixture(t, t.TempDir(), "policy.json", `{"example":{"checked_at":"2026-01-01T00:00:00Z","minimum":"2","releases":{"2":"2026-01-01T00:00:00Z"}}}`)
	err := runAuditImage("fixture", &AuditImageOptions{SBOMOnly: true, SBOMs: []string{"/inventory.json"}, UpdatePolicyURL: policy, FailOn: "critical", Format: "json"}, io.Discard, io.Discard)
	if err == nil || !strings.Contains(err.Error(), "package update deadlines failed") {
		t.Fatalf("deadline did not gate command: %v", err)
	}
}
