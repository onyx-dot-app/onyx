// Package audit runs dependency vulnerability audits across the repo's JS and
// Python lockfiles and open GitHub Dependabot security alerts, normalizes the
// results into a single model, suppresses accepted advisories via an S3-hosted
// allowlist, and reports them as text, JSON, or SARIF.
package audit

import (
	"fmt"
	"io"
	"path/filepath"
	"sort"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// Severity is a normalized advisory severity.
type Severity string

const (
	SeverityCritical Severity = "critical"
	SeverityHigh     Severity = "high"
	SeverityModerate Severity = "moderate"
	SeverityLow      Severity = "low"
	SeverityUnknown  Severity = "unknown"
)

// Source identifies which backend produced a finding.
const (
	SourceOSV        = "osv-scanner"
	SourceDependabot = "dependabot"
	SourceImage      = "osv-scanner-image"
)

// rank gives an orderable weight to a severity; higher is more severe.
func (s Severity) rank() int {
	switch s {
	case SeverityCritical:
		return 4
	case SeverityHigh:
		return 3
	case SeverityModerate:
		return 2
	case SeverityLow:
		return 1
	default:
		return 0
	}
}

// AtLeast reports whether s is at least as severe as other.
func (s Severity) AtLeast(other Severity) bool {
	return s.rank() >= other.rank()
}

// ParseSeverity normalizes a free-form severity label (e.g. from GHSA or
// Dependabot) to a Severity. "medium" maps to moderate.
func ParseSeverity(s string) Severity {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "critical":
		return SeverityCritical
	case "high":
		return SeverityHigh
	case "moderate", "medium":
		return SeverityModerate
	case "low":
		return SeverityLow
	default:
		return SeverityUnknown
	}
}

// SeverityFromCVSS maps a CVSS base score to a Severity bucket, following the
// CVSS v3 qualitative bands.
func SeverityFromCVSS(score float64) Severity {
	switch {
	case score >= 9.0:
		return SeverityCritical
	case score >= 7.0:
		return SeverityHigh
	case score >= 4.0:
		return SeverityModerate
	case score > 0.0:
		return SeverityLow
	default:
		return SeverityUnknown
	}
}

// Finding is a single normalized advisory affecting a dependency.
type Finding struct {
	ID        string   `json:"id"`
	Aliases   []string `json:"aliases,omitempty"`
	Ecosystem string   `json:"ecosystem"`
	Package   string   `json:"package"`
	Version   string   `json:"version,omitempty"`
	Severity  Severity `json:"severity"`
	Title     string   `json:"title,omitempty"`
	URL       string   `json:"url,omitempty"`
	Source    string   `json:"source"`
	FixedIn   string   `json:"fixed_in,omitempty"`
	// Manifest is the repo-relative lockfile/manifest the finding came from,
	// used for SARIF locations. May be empty.
	Manifest string `json:"manifest,omitempty"`
}

// Options configures an audit run.
type Options struct {
	Web        bool
	Python     bool
	Dependabot bool
	Format     string // text|json|sarif
	FailOn     Severity
	IgnoreURL  string
	Writer     io.Writer
}

// Result is the outcome of an audit run.
type Result struct {
	Findings []Finding `json:"findings"` // kept findings, after allowlist filtering
	Ignored  []Finding `json:"ignored"`  // findings suppressed by the allowlist
	Blocking []Finding `json:"blocking"` // kept findings at or above FailOn
}

// Run executes the selected audit backends, applies the allowlist, renders a
// report to opts.Writer, and returns the result. With no selector flags set,
// all backends are run.
func Run(opts Options) (*Result, error) {
	runAll := !opts.Web && !opts.Python && !opts.Dependabot
	scanWeb := runAll || opts.Web
	scanPython := runAll || opts.Python
	scanDependabot := runAll || opts.Dependabot

	var findings []Finding

	if scanWeb || scanPython {
		lockfiles, err := lockfilePaths(scanWeb, scanPython)
		if err != nil {
			return nil, fmt.Errorf("failed to locate lockfiles: %w", err)
		}
		fs, err := scanLockfiles(lockfiles)
		if err != nil {
			return nil, fmt.Errorf("dependency scan failed: %w", err)
		}
		findings = append(findings, fs...)
	}

	if scanDependabot {
		fs, err := auditDependabot()
		if err != nil {
			// When Dependabot is the only requested source, surface the error.
			// Otherwise the lockfile scan is the primary gate, so warn and
			// continue rather than fail the whole audit on an API hiccup.
			if opts.Dependabot && !opts.Web && !opts.Python {
				return nil, fmt.Errorf("dependabot audit failed: %w", err)
			}
			log.Warnf("Dependabot audit skipped: %v", err)
		} else {
			findings = append(findings, fs...)
		}
	}

	// Make manifest paths repo-relative for clean SARIF locations (best effort).
	if root, err := paths.GitRoot(); err == nil {
		for i := range findings {
			findings[i].Manifest = relManifest(root, findings[i].Manifest)
		}
	}

	ignores, err := FetchIgnores(opts.IgnoreURL)
	if err != nil {
		// Err toward blocking: proceed with an empty allowlist so unignored
		// criticals still fail the gate rather than slipping through.
		log.Warnf("Could not fetch allowlist from %s: %v (continuing with no suppressions)", opts.IgnoreURL, err)
		ignores = nil
	}

	findings = dedupeFindings(findings)

	kept, suppressed := applyIgnores(findings, ignores, time.Now())
	sortFindings(kept)
	sortFindings(suppressed)

	result := &Result{
		Findings: kept,
		Ignored:  suppressed,
		Blocking: blockingFindings(kept, opts.FailOn),
	}

	if err := render(opts.Writer, opts.Format, result); err != nil {
		return nil, err
	}
	return result, nil
}

// lockfilePaths returns the lockfiles to scan based on the selectors, skipping
// any that don't exist.
func lockfilePaths(web, python bool) ([]string, error) {
	root, err := paths.GitRoot()
	if err != nil {
		return nil, err
	}
	var candidates []string
	if web {
		candidates = append(candidates,
			filepath.Join(root, "web", "bun.lock"),
			filepath.Join(root, "bun.lock"),
		)
	}
	if python {
		candidates = append(candidates, filepath.Join(root, "uv.lock"))
	}
	var existing []string
	for _, c := range candidates {
		if fileExists(c) {
			existing = append(existing, c)
		} else {
			log.Debugf("Skipping missing lockfile %s", c)
		}
	}
	return existing, nil
}

// relManifest returns p relative to root when p is under it; otherwise returns
// p cleaned. Used to produce repo-relative SARIF URIs.
func relManifest(root, p string) string {
	if p == "" {
		return ""
	}
	if rel, err := filepath.Rel(root, p); err == nil && !strings.HasPrefix(rel, "..") {
		return filepath.ToSlash(rel)
	}
	return filepath.ToSlash(filepath.Clean(p))
}

// blockingFindings returns the findings at or above failOn, i.e. those that
// fail the audit and gate a deploy.
func blockingFindings(findings []Finding, failOn Severity) []Finding {
	var blocking []Finding
	for _, f := range findings {
		if f.Severity.AtLeast(failOn) {
			blocking = append(blocking, f)
		}
	}
	return blocking
}

// dedupeFindings removes duplicate findings keyed by id, ecosystem, package,
// and version. The same advisory can surface from more than one lockfile (e.g.
// the root and web bun.lock) or from both osv-scanner and Dependabot.
func dedupeFindings(findings []Finding) []Finding {
	seen := make(map[string]bool, len(findings))
	out := findings[:0]
	for _, f := range findings {
		key := strings.ToLower(f.ID) + "\x00" + strings.ToLower(f.Ecosystem) + "\x00" + f.Package + "\x00" + f.Version
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, f)
	}
	return out
}

// sortFindings orders findings by descending severity, then ecosystem, package,
// and id for stable, scannable output.
func sortFindings(findings []Finding) {
	sort.SliceStable(findings, func(i, j int) bool {
		a, b := findings[i], findings[j]
		if a.Severity.rank() != b.Severity.rank() {
			return a.Severity.rank() > b.Severity.rank()
		}
		if a.Ecosystem != b.Ecosystem {
			return a.Ecosystem < b.Ecosystem
		}
		if a.Package != b.Package {
			return a.Package < b.Package
		}
		return a.ID < b.ID
	})
}
