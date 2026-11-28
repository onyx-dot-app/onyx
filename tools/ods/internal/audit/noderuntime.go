package audit

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os/exec"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"deps.dev/util/semver"
)

const (
	nodeAdvisoriesURL       = "https://raw.githubusercontent.com/nodejs/security-wg/main/vuln/core/index.json"
	nodeReleasePolicySource = "node-security-releases"
	nodeReleasesURL         = "https://nodejs.org/dist/index.json"
)

type nodeRuntime struct {
	nodeImagePin
	Version string
}

type nodeAdvisory struct {
	Overview    string   `json:"overview"`
	CVEs        []string `json:"cve"`
	Vulnerable  string   `json:"vulnerable"`
	Patched     string   `json:"patched"`
	Description string   `json:"description"`
	Severity    string   `json:"severity"`
	URL         string   `json:"ref"`
	Platforms   []string `json:"affectedEnvironments"`
}

type nodeRelease struct {
	Version  string `json:"version"`
	Security bool   `json:"security"`
}

var stableNodeRelease = regexp.MustCompile(`^v([0-9]+)\.[0-9]+\.[0-9]+$`)

func scanNodeRuntimes(pins []nodeImagePin) (*Result, error) {
	runtimes := make([]nodeRuntime, 0, len(pins))
	for _, pin := range pins {
		cmd := exec.Command("docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--entrypoint", "node", pin.Image, "--version")
		output, err := cmd.Output()
		if err != nil {
			return nil, fmt.Errorf("read Node version from %s: %w", pin.Image, err)
		}
		runtimes = append(runtimes, nodeRuntime{pin, strings.TrimSpace(string(output))})
	}

	client := &http.Client{Timeout: 45 * time.Second}
	var advisories map[string]nodeAdvisory
	var releases []nodeRelease
	for _, feed := range []struct {
		url    string
		target any
	}{{nodeAdvisoriesURL, &advisories}, {nodeReleasesURL, &releases}} {
		body, _, err := httpGet(client, feed.url, nil)
		if err != nil {
			return nil, err
		}
		if err = json.Unmarshal(body, feed.target); err != nil {
			return nil, fmt.Errorf("decode %s: %w", feed.url, err)
		}
	}
	return nodeRuntimeReport(runtimes, advisories, releases)
}

func nodeRuntimeReport(runtimes []nodeRuntime, advisories map[string]nodeAdvisory, releases []nodeRelease) (*Result, error) {
	if len(runtimes) == 0 || len(advisories) == 0 || len(releases) == 0 {
		return nil, fmt.Errorf("missing Node runtime inventory, advisory feed or release feed")
	}
	published := map[string]*semver.Version{}
	lines := map[string][]*semver.Version{}
	floors := map[string]*semver.Version{}
	for _, release := range releases {
		parts := stableNodeRelease.FindStringSubmatch(release.Version)
		if parts == nil {
			continue
		}
		v, err := semver.NPM.Parse(release.Version[1:])
		if err != nil {
			return nil, err
		}
		published[release.Version] = v
		major := parts[1]
		lines[major] = append(lines[major], v)
		if prev := floors[major]; release.Security && (prev == nil || v.Compare(prev) > 0) {
			floors[major] = v
		}

	}
	if len(floors) == 0 {
		return nil, fmt.Errorf("no stable security releases in Node release feed")
	}
	result := &Result{ScannedPackages: []ScannedPackage{{Ecosystem: "Node.js", Package: "node"}}}
	for _, runtime := range runtimes {
		parts := stableNodeRelease.FindStringSubmatch(runtime.Version)
		v := published[runtime.Version]
		if parts == nil || v == nil || runtime.Image == "" || len(runtime.Consumers) == 0 {
			return nil, fmt.Errorf("incomplete or unknown Node runtime: %+v", runtime)
		}
		findings, err := nodeAdvisoryFindings(v, lines[parts[1]], advisories)
		if err != nil {
			return nil, err
		}
		if floor := floors[parts[1]]; floor != nil && v.Compare(floor) < 0 {
			findings = append(findings, Finding{
				ID:      "NODE-SECURITY-RELEASE-" + floor.String(),
				Title:   "Node runtime predates the latest security release on its major line",
				FixedIn: floor.String(), Severity: SeverityHigh,
				URL: nodeReleasesURL, Source: nodeReleasePolicySource,
			})
		}
		for _, f := range findings {
			f.Package = "node"
			f.Ecosystem = "Node.js"
			f.Version = v.String()
			for _, consumer := range runtime.Consumers {
				f.Manifest = consumer
				f.Image = runtime.Image
				result.Findings = append(result.Findings, f)
			}
		}
	}
	sortFindings(result.Findings)
	result.Blocking = blockingFindings(result.Findings, SeverityHigh)
	return result, nil
}

func nodeAdvisoryFindings(version *semver.Version, releases []*semver.Version, advisories map[string]nodeAdvisory) ([]Finding, error) {
	var findings []Finding
	for key, a := range advisories {
		if len(a.Platforms) > 0 && !slices.Contains(a.Platforms, "all") && !slices.Contains(a.Platforms, "linux") {
			continue
		}
		if strings.TrimSpace(a.Vulnerable) == "" || strings.TrimSpace(a.Patched) == "" {
			return nil, fmt.Errorf("missing Node version range for advisory %s", key)
		}
		affected, err := semver.NPM.ParseConstraint(strings.TrimSpace(a.Vulnerable))
		if err != nil {
			return nil, fmt.Errorf("parse Node advisory %s: %w", key, err)
		}
		if !affected.MatchVersion(version) {
			continue
		}
		patched, err := semver.NPM.ParseConstraint(strings.TrimSpace(a.Patched))
		if err != nil {
			return nil, fmt.Errorf("parse Node advisory %s: %w", key, err)
		}
		if patched.MatchVersion(version) {
			continue
		}
		if _, err := strconv.ParseUint(key, 10, 64); err != nil {
			return nil, fmt.Errorf("invalid Node advisory number %q", key)
		}
		for _, cve := range a.CVEs {
			if cve == "" || cveRe.FindString(cve) != cve {
				return nil, fmt.Errorf("invalid Node advisory CVE %q", cve)
			}
		}
		var firstFix *semver.Version
		for _, release := range releases {
			if release.Compare(version) > 0 && patched.MatchVersion(release) && (firstFix == nil || release.Compare(firstFix) < 0) {
				firstFix = release
			}
		}
		var fixedIn string
		if firstFix != nil {
			fixedIn = firstFix.String()
		}
		ids := a.CVEs
		if len(ids) == 0 {
			ids = []string{"NODE-CORE-" + key}
		}
		title := a.Description
		if title == "" {
			title = truncate(strings.Join(strings.Fields(a.Overview), " "), 200)
		}
		for _, id := range ids {
			findings = append(findings, Finding{
				ID: id, Title: title, FixedIn: fixedIn, Severity: ParseSeverity(a.Severity),
				URL: a.URL, Source: "node-security-wg",
			})
		}
	}
	return findings, nil
}
