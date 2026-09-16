package auditcmd

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	log "github.com/sirupsen/logrus"
)

// restoreLogger undoes the logger changes the root command's PersistentPreRun
// makes, so later tests see the default configuration.
func restoreLogger(t *testing.T) {
	t.Helper()
	level, formatter := log.GetLevel(), log.StandardLogger().Formatter
	t.Cleanup(func() {
		log.SetLevel(level)
		log.SetFormatter(formatter)
	})
}

// captureLog sends the standard logger to a buffer for the rest of the test.
// Logrus writes there, not to the command's stderr.
func captureLog(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	out := log.StandardLogger().Out
	log.SetOutput(&buf)
	t.Cleanup(func() { log.SetOutput(out) })
	return &buf
}

func TestRootCommand_flagsReachTheAudit(t *testing.T) {
	restoreLogger(t)
	logs := captureLog(t)
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	fakeDependabot(t, bin, criticalAlert)
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[{"id":"GHSA-aaaa-bbbb-cccc","reason":"accepted"}]}`)

	cmd := NewRootCommand("1.2.3", "abc123")
	var stdout, stderr bytes.Buffer
	cmd.SetOut(&stdout)
	cmd.SetErr(&stderr)
	cmd.SetArgs([]string{"--dependabot", "--format", "json", "--fail-on", "high", "--ignore-url", allowlist, "--debug"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}

	if log.GetLevel() != log.DebugLevel {
		t.Fatalf("expected --debug to enable debug logging, got %s", log.GetLevel())
	}
	var result struct {
		Findings []json.RawMessage `json:"findings"`
		Ignored  []struct {
			ID string `json:"id"`
		} `json:"ignored"`
	}
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		t.Fatalf("expected a JSON result on the command output: %v\n%s", err, stdout.String())
	}
	if len(result.Findings) != 0 || len(result.Ignored) != 1 || result.Ignored[0].ID != "GHSA-aaaa-bbbb-cccc" {
		t.Fatalf("expected the Dependabot alert to be suppressed by the allowlist, got %s", stdout.String())
	}
	if stderr.Len() != 0 {
		t.Fatalf("expected no text report on stderr with the JSON format, got %q", stderr.String())
	}
	if want := `level=debug msg="Suppressing GHSA-aaaa-bbbb-cccc`; !strings.Contains(logs.String(), want) {
		t.Fatalf("expected --debug to log the suppression %q, got %q", want, logs.String())
	}
}

func TestRootCommand_imageSubcommand(t *testing.T) {
	restoreLogger(t)
	const ref = "registry.example.test/onyx/backend:v1.2.3"
	bin := fakeBinDir(t)
	t.Setenv("TMPDIR", t.TempDir())
	fakeDockerWithEmptyImage(t, bin, ref)
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[]}`)

	cmd := NewRootCommand("1.2.3", "abc123")
	var stdout bytes.Buffer
	cmd.SetOut(&stdout)
	cmd.SetErr(&bytes.Buffer{})
	cmd.SetArgs([]string{"image", ref, "--format", "sarif", "--ignore-url", allowlist})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}

	if log.GetLevel() != log.InfoLevel {
		t.Fatalf("expected info logging without --debug, got %s", log.GetLevel())
	}
	if !strings.Contains(stdout.String(), `"version": "2.1.0"`) {
		t.Fatalf("expected a SARIF document for the image, got %q", stdout.String())
	}
}
