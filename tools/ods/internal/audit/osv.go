package audit

import (
	"errors"
	"log/slog"
	"os"
	"slices"
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

// fixedFor returns the lowest version above the installed one that no record
// in the group still lists as affected, so a bump to it ends every advisory
// of the finding. Candidates are the records' fixed versions for the package
// in its own ecosystem. Empty when no record names one the comparator can
// place.
func fixedFor(vulns []*osvschema.Vulnerability, ids []string, pkg models.PackageInfo) string {
	installed, err := semantic.Parse(pkg.Version, pkg.Ecosystem)
	if err != nil {
		return ""
	}
	idset := make(map[string]bool, len(ids))
	for _, id := range ids {
		idset[id] = true
	}
	var affected []*osvschema.Affected
	var candidates []string
	for _, v := range vulns {
		if !idset[v.GetId()] {
			continue
		}
		for _, aff := range v.GetAffected() {
			if !strings.EqualFold(aff.GetPackage().GetName(), pkg.Name) || !sameEcosystem(aff.GetPackage().GetEcosystem(), pkg.Ecosystem) {
				continue
			}
			affected = append(affected, aff)
			for _, r := range aff.GetRanges() {
				for _, e := range r.GetEvents() {
					if fixed := e.GetFixed(); fixed != "" {
						if c, err := installed.CompareStr(fixed); err == nil && c < 0 {
							candidates = append(candidates, fixed)
						}
					}
				}
			}
		}
	}
	slices.SortFunc(candidates, func(a, b string) int { return compareVersions(a, b, pkg.Ecosystem) })
	for _, candidate := range candidates {
		if !slices.ContainsFunc(affected, func(aff *osvschema.Affected) bool { return affectedAt(aff, candidate, pkg.Ecosystem) }) {
			return candidate
		}
	}
	return ""
}

// compareVersions orders two versions in the ecosystem's order, with an
// unparsable one first.
func compareVersions(a, b, ecosystem string) int {
	av, err := semantic.Parse(a, ecosystem)
	if err != nil {
		return -1
	}
	c, err := av.CompareStr(b)
	if err != nil {
		return 1
	}
	return c
}

// affectedAt reports whether the entry's ranges hold version: each
// "introduced" opens an interval that the next "fixed" closes exclusively or
// the next "last_affected" closes inclusively, and an open interval runs on.
func affectedAt(aff *osvschema.Affected, version, ecosystem string) bool {
	v, err := semantic.Parse(version, ecosystem)
	if err != nil {
		return false
	}
	for _, r := range aff.GetRanges() {
		open := false
		for _, e := range r.GetEvents() {
			switch {
			case e.GetIntroduced() != "":
				c, err := v.CompareStr(e.GetIntroduced())
				open = err == nil && c >= 0
			case e.GetFixed() != "":
				if c, err := v.CompareStr(e.GetFixed()); open && err == nil && c < 0 {
					return true
				}
				open = false
			case e.GetLastAffected() != "":
				if c, err := v.CompareStr(e.GetLastAffected()); open && err == nil && c <= 0 {
					return true
				}
				open = false
			}
		}
		if open {
			return true
		}
	}
	return false
}

// sameEcosystem compares OSV ecosystem names without their release suffix,
// so "Debian:13" and "Debian" match.
func sameEcosystem(a, b string) bool {
	base := func(s string) string { return strings.ToLower(strings.SplitN(s, ":", 2)[0]) }
	return base(a) == base(b)
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
