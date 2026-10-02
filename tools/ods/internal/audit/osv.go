package audit

import (
	"errors"
	"log/slog"
	"os"
	"strconv"
	"strings"

	"github.com/google/osv-scalibr/semantic"
	"github.com/google/osv-scanner/v2/pkg/models"
	"github.com/google/osv-scanner/v2/pkg/osvscanner"
	"github.com/ossf/osv-schema/bindings/go/osvschema"
)

func init() {
	// osv-scanner logs via slog. Route it to stderr at Warn+ so failures it only
	// reports through its logger (e.g. the docker stderr behind a "failed to run
	// docker command" image-pull error) stay visible, while findings still flow
	// to stdout via our own reporters. Warn+ keeps routine Info scan chatter out
	// and never collides with a --format=json/sarif report on stdout.
	osvscanner.SetLogger(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelWarn}))
}

// osvBaseURL is the canonical OSV.dev vulnerability page prefix.
const osvBaseURL = "https://osv.dev/vulnerability/"

// scanLockfiles runs osv-scanner (as a library) over the given lockfiles and
// maps the results into Findings. Returns nil when there are no lockfiles.
// With strict, lockfiles that yield no packages fail the scan, since a caller
// that reads absence as a fix must not trust an empty extraction.
func scanLockfiles(lockfiles []string, strict bool) ([]Finding, error) {
	if len(lockfiles) == 0 {
		return nil, nil
	}
	res, err := osvscanner.DoScan(osvscanner.ScannerActions{
		LockfilePaths: lockfiles,
	})
	if err != nil {
		// ErrVulnerabilitiesFound is the normal "found something" path; results
		// are still populated. ErrNoPackagesFound means nothing to scan.
		if errors.Is(err, osvscanner.ErrNoPackagesFound) && !strict {
			return nil, nil
		}
		if !errors.Is(err, osvscanner.ErrVulnerabilitiesFound) {
			return nil, err
		}
	}
	return findingsFromResults(res), nil
}

// findingsFromResults maps osv-scanner's VulnerabilityResults into Findings.
// It is pure (no I/O) so it can be unit tested against fixtures.
func findingsFromResults(res models.VulnerabilityResults) []Finding {
	var findings []Finding
	for _, src := range res.Results {
		for _, pkg := range src.Packages {
			for _, group := range pkg.Groups {
				f := findingFromGroup(group, pkg)
				f.Manifest = src.Source.Path
				findings = append(findings, f)
			}
		}
	}
	return findings
}

func findingFromGroup(group models.GroupInfo, pkg models.PackageVulns) Finding {
	id := representativeID(group.IDs)
	f := Finding{
		ID:        id,
		Aliases:   group.Aliases,
		Ecosystem: pkg.Package.Ecosystem,
		Package:   pkg.Package.Name,
		Version:   pkg.Package.Version,
		Severity:  severityForGroup(group, pkg),
		URL:       osvBaseURL + id,
		Source:    SourceOSV,
	}
	if vuln := findVuln(pkg.Vulnerabilities, group.IDs); vuln != nil {
		f.Title = vulnTitle(vuln)
	}
	f.FixedIn = fixedFor(pkg.Vulnerabilities, group.IDs, pkg.Package)
	return f
}

// fixedFor returns the version a bump must reach to end the finding: for each
// record in the group the lowest fixed version above the installed one, for
// the package in its own ecosystem, and across records the highest of those,
// since every record needs its own fix. Empty when no record names one the
// comparator can place.
func fixedFor(vulns []*osvschema.Vulnerability, ids []string, pkg models.PackageInfo) string {
	installed, err := semantic.Parse(pkg.Version, pkg.Ecosystem)
	if err != nil {
		return ""
	}
	idset := make(map[string]bool, len(ids))
	for _, id := range ids {
		idset[id] = true
	}
	best := ""
	for _, v := range vulns {
		if !idset[v.GetId()] {
			continue
		}
		fixed := ""
		for _, aff := range v.GetAffected() {
			if !strings.EqualFold(aff.GetPackage().GetName(), pkg.Name) || !sameEcosystem(aff.GetPackage().GetEcosystem(), pkg.Ecosystem) {
				continue
			}
			fixed = lowestFixedAbove(installed, aff, fixed, pkg.Ecosystem)
		}
		best = higherVersion(best, fixed, pkg.Ecosystem)
	}
	return best
}

// higherVersion returns the higher of two versions in the ecosystem's order,
// treating an empty or unparsable one as the lower.
func higherVersion(a, b, ecosystem string) string {
	if a == "" {
		return b
	}
	if b == "" {
		return a
	}
	av, err := semantic.Parse(a, ecosystem)
	if err != nil {
		return b
	}
	if c, err := av.CompareStr(b); err == nil && c < 0 {
		return b
	}
	return a
}

// sameEcosystem compares OSV ecosystem names without their release suffix,
// so "Debian:13" and "Debian" match.
func sameEcosystem(a, b string) bool {
	base := func(s string) string { return strings.ToLower(strings.SplitN(s, ":", 2)[0]) }
	return base(a) == base(b)
}

// lowestFixedAbove folds the affected entry's fixed versions into best,
// keeping the lowest one above installed.
func lowestFixedAbove(installed semantic.Version, aff *osvschema.Affected, best, ecosystem string) string {
	{
		for _, r := range aff.GetRanges() {
			for _, e := range r.GetEvents() {
				fixed := e.GetFixed()
				if fixed == "" {
					continue
				}
				if c, err := installed.CompareStr(fixed); err != nil || c >= 0 {
					continue
				}
				if best == "" {
					best = fixed
					continue
				}
				bestV, err := semantic.Parse(best, ecosystem)
				if c, cerr := bestV.CompareStr(fixed); err == nil && cerr == nil && c > 0 {
					best = fixed
				}
			}
		}
	}
	return best
}

// vulnTitle returns a one-line title for an advisory, preferring the summary
// and falling back to the first line of the details.
func vulnTitle(vuln *osvschema.Vulnerability) string {
	if summary := strings.TrimSpace(vuln.GetSummary()); summary != "" {
		return summary
	}
	details := strings.TrimSpace(vuln.GetDetails())
	if details == "" {
		return ""
	}
	if line, _, found := strings.Cut(details, "\n"); found {
		return strings.TrimSpace(line)
	}
	return details
}

// severityForGroup derives a Severity, preferring the CVSS-based MaxSeverity
// osv-scanner computes for the group, and falling back to the GHSA-style
// database_specific.severity label when no CVSS vector is available.
func severityForGroup(group models.GroupInfo, pkg models.PackageVulns) Severity {
	if group.MaxSeverity != "" {
		if score, err := strconv.ParseFloat(group.MaxSeverity, 64); err == nil {
			if sev := SeverityFromCVSS(score); sev != SeverityUnknown {
				return sev
			}
		}
	}
	if vuln := findVuln(pkg.Vulnerabilities, group.IDs); vuln != nil {
		if label := databaseSpecificSeverity(vuln); label != "" {
			return ParseSeverity(label)
		}
	}
	return SeverityUnknown
}

// databaseSpecificSeverity extracts a "severity" string (e.g. "CRITICAL") from
// the advisory's database_specific block, when present.
func databaseSpecificSeverity(vuln *osvschema.Vulnerability) string {
	ds := vuln.GetDatabaseSpecific()
	if ds == nil {
		return ""
	}
	if v, ok := ds.AsMap()["severity"].(string); ok {
		return v
	}
	return ""
}

// representativeID picks a stable display id for a group of aliased advisories.
func representativeID(ids []string) string {
	if len(ids) == 0 {
		return ""
	}
	return ids[0]
}

// findVuln returns the first vulnerability record whose id is in ids.
func findVuln(vulns []*osvschema.Vulnerability, ids []string) *osvschema.Vulnerability {
	idset := make(map[string]bool, len(ids))
	for _, id := range ids {
		idset[id] = true
	}
	for _, v := range vulns {
		if idset[v.GetId()] {
			return v
		}
	}
	return nil
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
