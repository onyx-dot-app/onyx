package auditcmd

import (
	"bytes"
	"errors"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

func stubCraftFC(t *testing.T, result *audit.Result, err error) *audit.CraftFCOptions {
	t.Helper()
	var got audit.CraftFCOptions
	orig := runCraftFC
	runCraftFC = func(opts audit.CraftFCOptions) (*audit.Result, error) {
		got = opts
		return result, err
	}
	t.Cleanup(func() { runCraftFC = orig })
	return &got
}

func TestRunAuditCraftFC(t *testing.T) {
	t.Run("clean run passes the options through", func(t *testing.T) {
		got := stubCraftFC(t, &audit.Result{}, nil)
		opts := &AuditCraftFCOptions{Dockerfile: "x/Dockerfile", Format: "json", FailOn: "high", IgnoreURL: "allow.json"}
		if err := runAuditCraftFC(opts, &bytes.Buffer{}, &bytes.Buffer{}); err != nil {
			t.Fatal(err)
		}
		if got.Dockerfile != "x/Dockerfile" || got.Format != "json" || got.FailOn != audit.SeverityHigh || got.IgnoreURL != "allow.json" {
			t.Fatalf("options = %+v", *got)
		}
	})
	t.Run("blocking findings fail", func(t *testing.T) {
		stubCraftFC(t, &audit.Result{Blocking: []audit.Finding{{ID: "GHSA-x"}}}, nil)
		err := runAuditCraftFC(&AuditCraftFCOptions{FailOn: "critical"}, &bytes.Buffer{}, &bytes.Buffer{})
		var blocking *blockingError
		if !errors.As(err, &blocking) {
			t.Fatalf("err = %v, want a blocking error", err)
		}
	})
	t.Run("a failed audit fails", func(t *testing.T) {
		stubCraftFC(t, nil, errors.New("feed down"))
		if err := runAuditCraftFC(&AuditCraftFCOptions{FailOn: "critical"}, &bytes.Buffer{}, &bytes.Buffer{}); err == nil {
			t.Fatal("expected an error")
		}
	})
	t.Run("an invalid threshold fails before the audit", func(t *testing.T) {
		stubCraftFC(t, nil, errors.New("must not run"))
		if err := runAuditCraftFC(&AuditCraftFCOptions{FailOn: "severe"}, &bytes.Buffer{}, &bytes.Buffer{}); err == nil {
			t.Fatal("expected an error")
		}
	})
}

func TestAuditCraftFCCommandDefaults(t *testing.T) {
	cmd := newAuditCraftFCCommand()
	if got := cmd.Flag("dockerfile").DefValue; got != audit.DefaultCraftFCDockerfile {
		t.Fatalf("--dockerfile default = %q", got)
	}
	if got := cmd.Flag("fail-on").DefValue; got != "critical" {
		t.Fatalf("--fail-on default = %q", got)
	}
}
