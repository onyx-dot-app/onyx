package audit

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/google/osv-scanner/v2/pkg/models"
	"github.com/google/osv-scanner/v2/pkg/osvscanner"
)

// ImageOptions configures a container image audit run.
type ImageOptions struct {
	SBOMOnly        bool
	Image           string
	SBOMs           []string // Required inventory paths inside the image.
	UpdatePolicyURL string
	Format          string // comma-separated list of text|json|sarif
	FailOn          Severity
	IgnoreURL       string
	// Strict fails a scan that extracts no packages, for callers that read a
	// missing finding as a resolved one. Every image ships OS packages.
	Strict bool
	// Stdout/Stderr route the requested formats; see Options and renderReport.
	Stdout io.Writer
	Stderr io.Writer
}

var scanOSImage = scanImage

var (
	containerScan        = osvscanner.DoContainerScan
	scanPyPIRequirements = scanRequirements
	requirementsScan     = scanLockfiles
)

// pypiToolsFromCrates maps crates.io names the image scanner records for
// Rust-built PyPI tools to their PyPI names. Their binaries carry
// cargo-auditable data, so the scanner sees a crate, while the advisories
// are filed on PyPI.
var pypiToolsFromCrates = map[string]string{"uv": "uv"}

// RunImage scans a container image for known vulnerabilities, applies the same
// S3 allowlist used by Run, renders a report to opts.Stdout/opts.Stderr, and
// returns the result. Findings at or above opts.FailOn are reported as Blocking,
// which is how it gates a release.
func RunImage(opts ImageOptions) (*Result, error) {
	if opts.SBOMOnly && len(opts.SBOMs) == 0 {
		return nil, fmt.Errorf("SBOM-only audit requires an inventory")
	}
	var findings []Finding
	var err error
	if !opts.SBOMOnly {
		findings, err = scanOSImage(opts.Image, opts.Strict)
		if err != nil {
			return nil, fmt.Errorf("image scan failed: %w", err)
		}
	}

	var updates []UpdateStatus
	var packages []ScannedPackage
	var policy UpdatePolicy
	if len(opts.SBOMs) > 0 && opts.UpdatePolicyURL != "" {
		policy, err = ReadUpdatePolicy(opts.UpdatePolicyURL)
		if err != nil {
			return nil, err
		}
	}
	for _, inventory := range opts.SBOMs {
		extra, err := scanSBOM(opts.Image, inventory, opts.Stderr)
		if err != nil {
			return nil, err
		}
		findings = append(findings, extra.Findings...)
		if policy != nil {
			for _, component := range extra.Components {
				entry, ok := policy[component.Name]
				if !ok {
					return nil, fmt.Errorf("missing update policy for %s", component.Name)
				}
				status, err := CheckUpdate(component.Name, component.Version, entry, time.Now())
				if err != nil {
					return nil, err
				}
				updates = append(updates, status)
			}
		}
		packages = append(packages, extra.ScannedPackages...)
	}

	result := filterFindings(findings, opts.IgnoreURL, opts.FailOn)
	result.ScannedPackages = packages
	result.Updates = updates
	if err := renderReport(opts.Stdout, opts.Stderr, opts.Format, result); err != nil {
		return nil, err
	}
	return result, nil
}

// filterFindings dedupes findings, applies the allowlist at ignoreURL and marks
// the kept findings at or above failOn as blocking.
func filterFindings(findings []Finding, ignoreURL string, failOn Severity) *Result {
	ignores, err := FetchIgnores(ignoreURL)
	if err != nil {
		// Err toward blocking: proceed with an empty allowlist so unignored
		// criticals still fail the gate rather than slipping through.
		log.Warnf("Could not fetch allowlist from %s: %v (continuing with no suppressions)", ignoreURL, err)
		ignores = nil
	}

	findings = dedupeFindings(findings)

	kept, suppressed := applyIgnores(findings, ignores, time.Now())
	sortFindings(kept)
	sortFindings(suppressed)

	return &Result{
		Findings: kept,
		Ignored:  suppressed,
		Blocking: blockingFindings(kept, failOn),
	}
}

// scanImage runs osv-scanner's layer-aware container scanner (as a library)
// over ref and maps the results into Findings. ref may be a remote image, which
// is pulled using the ambient Docker credentials.
func scanImage(ref string, strict bool) ([]Finding, error) {
	res, err := containerScan(osvscanner.ScannerActions{
		Image: ref,
		// Fetch the OSV databases so matching works on a fresh CI runner
		// regardless of whether container scanning defaults to online or offline.
		DownloadDatabases: true,
		// List packages with no findings too, so the PyPI pass below sees them.
		ShowAllPackages: true,
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
	findings := imageFindingsFromResults(res, ref)
	if reqs := pypiRequirementsFromCrates(res); len(reqs) > 0 {
		extra, err := scanPyPIRequirements(reqs)
		if err != nil {
			return nil, fmt.Errorf("scan PyPI tools in %s: %w", ref, err)
		}
		for i := range extra {
			extra[i].Source = SourceImage
			extra[i].Manifest = ref
		}
		findings = append(findings, extra...)
	}
	return findings, nil
}

// pypiRequirementsFromCrates returns a pinned PyPI requirement for each
// crates.io package in res that is a PyPI tool.
func pypiRequirementsFromCrates(res models.VulnerabilityResults) []string {
	seen := map[string]bool{}
	var reqs []string
	for _, src := range res.Results {
		for _, pkg := range src.Packages {
			name, ok := pypiToolsFromCrates[pkg.Package.Name]
			if !ok || pkg.Package.Ecosystem != "crates.io" || pkg.Package.Version == "" {
				continue
			}
			req := name + "==" + pkg.Package.Version
			if !seen[req] {
				seen[req] = true
				reqs = append(reqs, req)
			}
		}
	}
	sort.Strings(reqs)
	return reqs
}

// scanRequirements matches pinned PyPI requirements against OSV.
func scanRequirements(reqs []string) ([]Finding, error) {
	dir, err := os.MkdirTemp("", "ods-pypi-*")
	if err != nil {
		return nil, err
	}
	defer func() { _ = os.RemoveAll(dir) }()
	path := filepath.Join(dir, "requirements.txt")
	if err := os.WriteFile(path, []byte(strings.Join(reqs, "\n")+"\n"), 0o600); err != nil {
		return nil, err
	}
	return requirementsScan([]string{path}, true)
}

// imageFindingsFromResults maps osv-scanner's container results into Findings,
// tagging them as image findings and pointing their manifest at the ref. Pure
// (no I/O) so it can be unit tested.
func imageFindingsFromResults(res models.VulnerabilityResults, ref string) []Finding {
	findings := findingsFromResults(res)
	for i := range findings {
		findings[i].Source = SourceImage
		findings[i].Manifest = ref
	}
	return findings
}
