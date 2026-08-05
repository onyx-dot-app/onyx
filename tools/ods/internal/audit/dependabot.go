package audit

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
)

// dependabotAlert is the subset of the GitHub Dependabot alerts API response we
// care about. See:
// https://docs.github.com/rest/dependabot/alerts#list-dependabot-alerts-for-a-repository
type dependabotAlert struct {
	State      string `json:"state"`
	HTMLURL    string `json:"html_url"`
	Dependency struct {
		Package struct {
			Ecosystem string `json:"ecosystem"`
			Name      string `json:"name"`
		} `json:"package"`
		ManifestPath string `json:"manifest_path"`
	} `json:"dependency"`
	SecurityAdvisory struct {
		GHSAID   string `json:"ghsa_id"`
		CVEID    string `json:"cve_id"`
		Summary  string `json:"summary"`
		Severity string `json:"severity"`
	} `json:"security_advisory"`
	SecurityVulnerability struct {
		Severity            string `json:"severity"`
		FirstPatchedVersion struct {
			Identifier string `json:"identifier"`
		} `json:"first_patched_version"`
	} `json:"security_vulnerability"`
}

// auditDependabot queries open Dependabot security alerts for the current repo
// via the GitHub CLI and maps them into Findings.
func auditDependabot() ([]Finding, error) {
	// {owner}/{repo} is resolved by gh from the repo's git remote. --paginate
	// merges array pages into a single JSON array.
	cmd := exec.Command("gh", "api",
		"repos/{owner}/{repo}/dependabot/alerts",
		"--paginate",
		"-f", "state=open",
		"-f", "per_page=100",
	)
	out, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			stderr := strings.TrimSpace(string(exitErr.Stderr))
			if strings.Contains(stderr, "404") || strings.Contains(stderr, "Not Found") {
				return nil, fmt.Errorf("gh api dependabot/alerts returned 404: ensure Dependabot alerts are enabled and the token has 'security_events: read' (or repo admin) access: %s", stderr)
			}
			return nil, fmt.Errorf("gh api dependabot/alerts failed: %w: %s", err, stderr)
		}
		return nil, fmt.Errorf("gh api dependabot/alerts failed: %w", err)
	}
	return parseDependabotAlerts(out)
}

// parseDependabotAlerts maps the alerts JSON into Findings, keeping only open
// alerts. It is pure so it can be unit tested against fixtures.
func parseDependabotAlerts(data []byte) ([]Finding, error) {
	var alerts []dependabotAlert
	if err := json.Unmarshal(data, &alerts); err != nil {
		return nil, fmt.Errorf("failed to parse dependabot alerts: %w", err)
	}

	var findings []Finding
	for _, a := range alerts {
		if a.State != "open" {
			continue
		}

		id := a.SecurityAdvisory.GHSAID
		if id == "" {
			id = a.SecurityAdvisory.CVEID
		}

		label := a.SecurityAdvisory.Severity
		if label == "" {
			label = a.SecurityVulnerability.Severity
		}

		var aliases []string
		if a.SecurityAdvisory.GHSAID != "" {
			aliases = append(aliases, a.SecurityAdvisory.GHSAID)
		}
		if a.SecurityAdvisory.CVEID != "" {
			aliases = append(aliases, a.SecurityAdvisory.CVEID)
		}

		findings = append(findings, Finding{
			ID:        id,
			Aliases:   aliases,
			Ecosystem: a.Dependency.Package.Ecosystem,
			Package:   a.Dependency.Package.Name,
			Severity:  ParseSeverity(label),
			Title:     a.SecurityAdvisory.Summary,
			URL:       a.HTMLURL,
			Source:    SourceDependabot,
			FixedIn:   a.SecurityVulnerability.FirstPatchedVersion.Identifier,
			Manifest:  strings.TrimPrefix(a.Dependency.ManifestPath, "/"),
		})
	}
	return findings, nil
}
