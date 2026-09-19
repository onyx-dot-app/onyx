package audit

import (
	"strings"
	"testing"
)

const dependabotFixture = `[
  {
    "state": "open",
    "html_url": "https://github.com/onyx-dot-app/onyx/security/dependabot/1",
    "dependency": {
      "package": {"ecosystem": "pip", "name": "requests"},
      "manifest_path": "/pyproject.toml"
    },
    "security_advisory": {
      "ghsa_id": "GHSA-aaaa-bbbb-cccc",
      "cve_id": "CVE-2026-0001",
      "summary": "Requests SSRF",
      "severity": "critical"
    },
    "security_vulnerability": {
      "severity": "critical",
      "first_patched_version": {"identifier": "2.99.0"}
    }
  },
  {
    "state": "open",
    "html_url": "https://github.com/onyx-dot-app/onyx/security/dependabot/2",
    "dependency": {"package": {"ecosystem": "npm", "name": "left-pad"}},
    "security_advisory": {
      "ghsa_id": "GHSA-dddd",
      "cve_id": "",
      "summary": "left-pad medium",
      "severity": "medium"
    },
    "security_vulnerability": {"severity": "medium"}
  },
  {
    "state": "dismissed",
    "html_url": "https://github.com/onyx-dot-app/onyx/security/dependabot/3",
    "dependency": {"package": {"ecosystem": "npm", "name": "ignored-pkg"}},
    "security_advisory": {"ghsa_id": "GHSA-eeee", "severity": "critical", "summary": "dismissed"},
    "security_vulnerability": {"severity": "critical"}
  }
]`

func TestParseDependabotAlerts(t *testing.T) {
	findings, err := parseDependabotAlerts([]byte(dependabotFixture))
	if err != nil {
		t.Fatalf("parseDependabotAlerts: %v", err)
	}

	// The dismissed alert must be dropped.
	if len(findings) != 2 {
		t.Fatalf("got %d findings, want 2 (dismissed dropped)", len(findings))
	}

	first := findings[0]
	if first.ID != "GHSA-aaaa-bbbb-cccc" {
		t.Errorf("first id = %q, want GHSA preferred over CVE", first.ID)
	}
	if first.Severity != SeverityCritical {
		t.Errorf("first severity = %q", first.Severity)
	}
	if first.Ecosystem != "pip" || first.Package != "requests" {
		t.Errorf("first package wrong: %+v", first)
	}
	if first.FixedIn != "2.99.0" {
		t.Errorf("first fixedIn = %q", first.FixedIn)
	}
	if first.Manifest != "pyproject.toml" {
		t.Errorf("first manifest = %q, want leading slash trimmed", first.Manifest)
	}
	if first.Source != SourceDependabot {
		t.Errorf("first source = %q", first.Source)
	}
	wantAliases := map[string]bool{"GHSA-aaaa-bbbb-cccc": true, "CVE-2026-0001": true}
	for _, a := range first.Aliases {
		if !wantAliases[a] {
			t.Errorf("unexpected alias %q", a)
		}
	}
	if len(first.Aliases) != 2 {
		t.Errorf("first aliases = %v, want ghsa+cve", first.Aliases)
	}

	second := findings[1]
	if second.Severity != SeverityModerate {
		t.Errorf("second severity = %q, want moderate (medium normalized)", second.Severity)
	}
}

func TestParseDependabotAlerts_fallbacks(t *testing.T) {
	const alerts = `[{
	  "state": "open",
	  "dependency": {"package": {"ecosystem": "npm", "name": "lodash"}},
	  "security_advisory": {"cve_id": "CVE-2026-0002", "summary": "no ghsa"},
	  "security_vulnerability": {"severity": "high"}
	}]`
	findings, err := parseDependabotAlerts([]byte(alerts))
	if err != nil {
		t.Fatalf("parseDependabotAlerts: %v", err)
	}
	if len(findings) != 1 {
		t.Fatalf("expected 1 finding, got %d", len(findings))
	}
	f := findings[0]
	if f.ID != "CVE-2026-0002" {
		t.Errorf("expected the CVE id when there is no GHSA id, got %q", f.ID)
	}
	if len(f.Aliases) != 1 || f.Aliases[0] != "CVE-2026-0002" {
		t.Errorf("expected aliases [CVE-2026-0002], got %v", f.Aliases)
	}
	if f.Severity != SeverityHigh {
		t.Errorf("expected the vulnerability severity when the advisory has none, got %q", f.Severity)
	}
}

func TestAuditDependabot_failures(t *testing.T) {
	cases := []struct {
		name   string
		script string
		want   string
	}{
		{
			name:   "alerts disabled",
			script: "echo 'gh: Not Found (HTTP 404)' >&2\nexit 1",
			want:   "returned 404: ensure Dependabot alerts are enabled and the token has 'security_events: read' (or repo admin) access: gh: Not Found (HTTP 404)",
		},
		{
			name:   "other gh failure",
			script: "echo 'gh: Bad credentials (HTTP 401)' >&2\nexit 4",
			want:   "gh api dependabot/alerts failed: exit status 4: gh: Bad credentials (HTTP 401)",
		},
		{
			name:   "unparseable output",
			script: `echo '{"message": "not a list"}'`,
			want:   "failed to parse dependabot alerts",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			bin := fakeBinDir(t)
			writeFakeCommand(t, bin, "gh", tc.script)
			findings, err := auditDependabot()
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("expected an error containing %q, got findings %+v and error %v", tc.want, findings, err)
			}
		})
	}

	t.Run("gh not installed", func(t *testing.T) {
		t.Setenv("PATH", t.TempDir())
		_, err := auditDependabot()
		if err == nil || !strings.HasPrefix(err.Error(), "gh api dependabot/alerts failed: ") {
			t.Fatalf("expected a gh failure, got %v", err)
		}
	})
}
