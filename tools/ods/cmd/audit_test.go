package cmd

import (
	"bytes"
	"io"
	"os"
	"testing"

	log "github.com/sirupsen/logrus"
)

func TestAuditWritersDefault(t *testing.T) {
	stdout, stderr := auditWriters(false)
	if stdout != io.Writer(os.Stdout) || stderr != io.Writer(os.Stderr) {
		t.Fatalf("auditWriters(false) = %v, %v; want os.Stdout, os.Stderr", stdout, stderr)
	}
}

// Quiet must silence the report streams and logrus, so a run writes nothing and
// only the exit code reports the verdict.
func TestAuditWritersQuiet(t *testing.T) {
	prev := log.StandardLogger().Out
	t.Cleanup(func() { log.SetOutput(prev) })

	var logged bytes.Buffer
	log.SetOutput(&logged)

	stdout, stderr := auditWriters(true)
	if stdout != io.Discard || stderr != io.Discard {
		t.Fatalf("auditWriters(true) = %v, %v; want io.Discard twice", stdout, stderr)
	}

	log.Warnf("allowlist fetch failed")
	log.Errorf("1 finding(s) must be resolved")
	if logged.Len() != 0 {
		t.Fatalf("quiet run logged %q; want nothing", logged.String())
	}
}

func TestAuditQuietFlagRegistered(t *testing.T) {
	audit := NewAuditCommand()
	if f := audit.Flags().Lookup("quiet"); f == nil || f.Shorthand != "q" {
		t.Fatalf("ods audit is missing a --quiet/-q flag")
	}

	image, _, err := audit.Find([]string{"image"})
	if err != nil {
		t.Fatalf("finding `ods audit image`: %v", err)
	}
	if f := image.Flags().Lookup("quiet"); f == nil || f.Shorthand != "q" {
		t.Fatalf("ods audit image is missing a --quiet/-q flag")
	}
}
