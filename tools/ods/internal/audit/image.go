package audit

import (
	"errors"
	"fmt"
	"io"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/google/osv-scanner/v2/pkg/models"
	"github.com/google/osv-scanner/v2/pkg/osvscanner"
)

// ImageOptions configures a container image audit run.
type ImageOptions struct {
	Image     string
	Format    string // text|json|sarif
	FailOn    Severity
	IgnoreURL string
	Writer    io.Writer
}

// RunImage scans a container image for known vulnerabilities, applies the same
// S3 allowlist used by Run, renders a report to opts.Writer, and returns the
// result. Findings at or above opts.FailOn are reported as Blocking, which is
// how it gates a release.
func RunImage(opts ImageOptions) (*Result, error) {
	findings, err := scanImage(opts.Image)
	if err != nil {
		return nil, fmt.Errorf("image scan failed: %w", err)
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

// scanImage runs osv-scanner's layer-aware container scanner (as a library)
// over ref and maps the results into Findings. ref may be a remote image, which
// is pulled using the ambient Docker credentials.
func scanImage(ref string) ([]Finding, error) {
	res, err := osvscanner.DoContainerScan(osvscanner.ScannerActions{
		Image: ref,
		// Fetch the OSV databases so matching works on a fresh CI runner
		// regardless of whether container scanning defaults to online or offline.
		DownloadDatabases: true,
	})
	if err != nil {
		// ErrVulnerabilitiesFound is the normal "found something" path; results
		// are still populated. ErrNoPackagesFound means nothing to scan.
		if errors.Is(err, osvscanner.ErrNoPackagesFound) {
			return nil, nil
		}
		if !errors.Is(err, osvscanner.ErrVulnerabilitiesFound) {
			return nil, err
		}
	}
	return imageFindingsFromResults(res, ref), nil
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
