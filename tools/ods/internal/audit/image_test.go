package audit

import (
	"testing"

	"github.com/google/osv-scanner/v2/pkg/models"
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
