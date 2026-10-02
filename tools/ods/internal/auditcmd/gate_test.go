package auditcmd

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// fakeGateScans swaps the gate's scans for canned results and records the
// images it was asked to scan.
func fakeGateScans(t *testing.T, deps *audit.Result, depsErr error, images map[string]*audit.Result, imageErr error) *[]string {
	t.Helper()
	origDeps, origImage := runDeps, runImage
	t.Cleanup(func() { runDeps, runImage = origDeps, origImage })
	var scanned []string
	runDeps = func(audit.Options) (*audit.Result, error) { return deps, depsErr }
	runImage = func(opts audit.ImageOptions) (*audit.Result, error) {
		scanned = append(scanned, opts.Image)
		if imageErr != nil {
			return nil, imageErr
		}
		return images[opts.Image], nil
	}
	return &scanned
}

func writeGateScript(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "base-image-ref.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestRunAuditGate_sumsBlockingAcrossScans(t *testing.T) {
	critical := audit.Finding{ID: "GHSA-1", Severity: audit.SeverityCritical}
	scanned := fakeGateScans(t, &audit.Result{Blocking: []audit.Finding{critical}}, nil, map[string]*audit.Result{
		"dhi.io/node:24@sha256:a":     {},
		"dhi.io/python:3.13@sha256:b": {Blocking: []audit.Finding{critical, critical}},
		"onyx-backend-os:audit":       {},
	}, nil)
	script := writeGateScript(t, `case "$1" in web) echo "dhi.io/node:24@sha256:a ";; model-server) echo dhi.io/python:3.13@sha256:b;; backend) echo onyx-backend-os:audit;; esac`)

	var stdout, stderr bytes.Buffer
	err := runAuditGate(&AuditGateOptions{Script: script}, &stdout, &stderr)

	var blocking *blockingError
	if !errors.As(err, &blocking) || blocking.count != 3 {
		t.Fatalf("expected three blocking findings across the scans, got %v", err)
	}
	want := []string{"dhi.io/node:24@sha256:a", "dhi.io/python:3.13@sha256:b", "onyx-backend-os:audit"}
	if strings.Join(*scanned, ",") != strings.Join(want, ",") {
		t.Fatalf("scanned %v, want %v in order", *scanned, want)
	}
	if !strings.Contains(stderr.String(), "Scanning backend: onyx-backend-os:audit") {
		t.Fatalf("expected each scan named on stderr, got:\n%s", stderr.String())
	}
}

func TestRunAuditGate_cleanPasses(t *testing.T) {
	fakeGateScans(t, &audit.Result{}, nil, map[string]*audit.Result{"a": {}, "b": {}, "c": {}}, nil)
	script := writeGateScript(t, `case "$1" in web) echo a;; model-server) echo b;; backend) echo c;; esac`)
	if err := runAuditGate(&AuditGateOptions{Script: script}, &bytes.Buffer{}, &bytes.Buffer{}); err != nil {
		t.Fatalf("expected a clean gate to pass, got %v", err)
	}
}

func TestRunAuditGate_failures(t *testing.T) {
	t.Run("dependency audit error", func(t *testing.T) {
		fakeGateScans(t, nil, errors.New("osv down"), nil, nil)
		err := runAuditGate(&AuditGateOptions{Script: "unused"}, &bytes.Buffer{}, &bytes.Buffer{})
		if err == nil || !strings.Contains(err.Error(), "Audit failed: osv down") {
			t.Fatalf("expected the audit error, got %v", err)
		}
	})
	t.Run("image cannot be resolved", func(t *testing.T) {
		fakeGateScans(t, &audit.Result{}, nil, nil, nil)
		script := writeGateScript(t, `echo "no docker" >&2; exit 3`)
		err := runAuditGate(&AuditGateOptions{Script: script}, &bytes.Buffer{}, &bytes.Buffer{})
		if err == nil || !strings.Contains(err.Error(), "Failed to resolve the web image") {
			t.Fatalf("expected the resolve error, got %v", err)
		}
	})
	t.Run("image audit error", func(t *testing.T) {
		fakeGateScans(t, &audit.Result{}, nil, nil, errors.New("pull denied"))
		script := writeGateScript(t, `echo img`)
		err := runAuditGate(&AuditGateOptions{Script: script}, &bytes.Buffer{}, &bytes.Buffer{})
		if err == nil || !strings.Contains(err.Error(), "Image audit of web failed: pull denied") {
			t.Fatalf("expected the image audit error, got %v", err)
		}
	})
}
