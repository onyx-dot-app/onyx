package audit

import "testing"

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
