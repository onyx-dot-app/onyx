package audit

import (
	"slices"
	"testing"

	"github.com/google/osv-scanner/v2/pkg/models"
	"github.com/google/osv-scanner/v2/pkg/osvscanner"
	"github.com/ossf/osv-schema/bindings/go/osvschema"
)

func TestImageFindingsFromResults(t *testing.T) {
	const ref = "docker.io/onyxdotapp/onyx-backend:v1.2.3"
	res := models.VulnerabilityResults{
		Results: []models.PackageSource{
			{
				// Container scans report a layer/package path here; image
				// findings should override it with the image ref.
				Source: models.SourceInfo{Path: "sha256:deadbeef"},
				Packages: []models.PackageVulns{
					{
						Package: models.PackageInfo{Name: "zlib1g", Version: "1:1.2.13.dfsg-1", Ecosystem: "Debian:12"},
						Groups: []models.GroupInfo{
							{IDs: []string{"CVE-2023-45853"}, Aliases: []string{"CVE-2023-45853"}, MaxSeverity: "9.8"},
						},
						Vulnerabilities: []*osvschema.Vulnerability{
							{Id: "CVE-2023-45853", Summary: "MiniZip integer overflow"},
						},
					},
				},
			},
		},
	}

	findings := imageFindingsFromResults(res, ref)
	if len(findings) != 1 {
		t.Fatalf("got %d findings, want 1", len(findings))
	}

	f := findings[0]
	if f.Source != SourceImage {
		t.Errorf("source = %q, want %q", f.Source, SourceImage)
	}
	if f.Manifest != ref {
		t.Errorf("manifest = %q, want image ref %q", f.Manifest, ref)
	}
	if f.Severity != SeverityCritical {
		t.Errorf("severity = %q, want critical", f.Severity)
	}
	if f.ID != "CVE-2023-45853" || f.Ecosystem != "Debian:12" {
		t.Errorf("finding mapping wrong: %+v", f)
	}
	if f.Title != "MiniZip integer overflow" {
		t.Errorf("title = %q", f.Title)
	}
}

// The uv binary carries cargo-auditable data, so the image scanner records it
// as a crates.io crate, while its advisories are filed on PyPI.
func TestScanImage_matchesRustBuiltPyPIToolsOnPyPI(t *testing.T) {
	const ref = "docker.io/onyxdotapp/craft-runtime:v1.2.3"
	t.Cleanup(func() {
		containerScan = osvscanner.DoContainerScan
		scanPyPIRequirements = scanRequirements
	})
	containerScan = func(actions osvscanner.ScannerActions) (models.VulnerabilityResults, error) {
		if !actions.ShowAllPackages {
			t.Error("container scan must list packages with no findings")
		}
		return models.VulnerabilityResults{Results: []models.PackageSource{{
			Source: models.SourceInfo{Path: "/usr/local/bin/uv"},
			Packages: []models.PackageVulns{
				{Package: models.PackageInfo{Name: "uv", Version: "0.11.25", Ecosystem: "crates.io"}},
				{Package: models.PackageInfo{Name: "tokio", Version: "1.50.0", Ecosystem: "crates.io"}},
			},
		}}}, nil
	}
	var gotReqs []string
	scanPyPIRequirements = func(reqs []string) ([]Finding, error) {
		gotReqs = reqs
		return []Finding{{ID: "PYSEC-2026-4321", Ecosystem: "PyPI", Package: "uv", Version: "0.11.25",
			Severity: SeverityCritical, Source: SourceOSV, Manifest: "/tmp/requirements.txt"}}, nil
	}

	findings, err := scanImage(ref, true)
	if err != nil {
		t.Fatalf("scanImage: %v", err)
	}
	if want := []string{"uv==0.11.25"}; !slices.Equal(gotReqs, want) {
		t.Errorf("PyPI requirements = %v, want %v", gotReqs, want)
	}
	if len(findings) != 1 {
		t.Fatalf("got %d findings, want 1: %+v", len(findings), findings)
	}
	if f := findings[0]; f.ID != "PYSEC-2026-4321" || f.Source != SourceImage || f.Manifest != ref {
		t.Errorf("finding = %+v, want PYSEC-2026-4321 from the image", f)
	}
}
