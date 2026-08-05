package audit

import (
	"testing"

	"github.com/google/osv-scanner/v2/pkg/models"
	"github.com/ossf/osv-schema/bindings/go/osvschema"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestSeverityFromCVSS(t *testing.T) {
	cases := []struct {
		score float64
		want  Severity
	}{
		{10.0, SeverityCritical},
		{9.0, SeverityCritical},
		{8.9, SeverityHigh},
		{7.0, SeverityHigh},
		{6.9, SeverityModerate},
		{4.0, SeverityModerate},
		{3.9, SeverityLow},
		{0.1, SeverityLow},
		{0.0, SeverityUnknown},
		{-1.0, SeverityUnknown},
	}
	for _, tc := range cases {
		if got := SeverityFromCVSS(tc.score); got != tc.want {
			t.Errorf("SeverityFromCVSS(%v) = %q, want %q", tc.score, got, tc.want)
		}
	}
}

func dbSpecificSeverity(t *testing.T, label string) *structpb.Struct {
	t.Helper()
	s, err := structpb.NewStruct(map[string]any{"severity": label})
	if err != nil {
		t.Fatalf("NewStruct: %v", err)
	}
	return s
}

func TestFindingsFromResults(t *testing.T) {
	res := models.VulnerabilityResults{
		Results: []models.PackageSource{
			{
				Source: models.SourceInfo{Path: "/repo/web/bun.lock"},
				Packages: []models.PackageVulns{
					{
						Package: models.PackageInfo{Name: "lodash", Version: "4.17.0", Ecosystem: "npm"},
						Groups: []models.GroupInfo{
							{IDs: []string{"GHSA-aaaa"}, Aliases: []string{"GHSA-aaaa", "CVE-2020-1"}, MaxSeverity: "9.8"},
						},
						Vulnerabilities: []*osvschema.Vulnerability{
							{Id: "GHSA-aaaa", Summary: "Prototype pollution"},
						},
					},
				},
			},
			{
				Source: models.SourceInfo{Path: "/repo/uv.lock"},
				Packages: []models.PackageVulns{
					{
						Package: models.PackageInfo{Name: "torch", Version: "2.9.1", Ecosystem: "PyPI"},
						Groups: []models.GroupInfo{
							// No CVSS score -> fall back to database_specific.severity.
							{IDs: []string{"PYSEC-2026-1"}, Aliases: []string{"PYSEC-2026-1"}, MaxSeverity: ""},
						},
						Vulnerabilities: []*osvschema.Vulnerability{
							{
								Id:               "PYSEC-2026-1",
								Details:          "First line of details.\nSecond line.",
								DatabaseSpecific: dbSpecificSeverity(t, "HIGH"),
							},
						},
					},
				},
			},
		},
	}

	findings := findingsFromResults(res)
	if len(findings) != 2 {
		t.Fatalf("got %d findings, want 2", len(findings))
	}

	npm := findings[0]
	if npm.ID != "GHSA-aaaa" || npm.Severity != SeverityCritical || npm.Ecosystem != "npm" {
		t.Errorf("npm finding wrong: %+v", npm)
	}
	if npm.Title != "Prototype pollution" {
		t.Errorf("npm title = %q", npm.Title)
	}
	if npm.Manifest != "/repo/web/bun.lock" {
		t.Errorf("npm manifest = %q", npm.Manifest)
	}
	if npm.URL != osvBaseURL+"GHSA-aaaa" {
		t.Errorf("npm url = %q", npm.URL)
	}
	if len(npm.Aliases) != 2 {
		t.Errorf("npm aliases = %v", npm.Aliases)
	}

	py := findings[1]
	if py.Severity != SeverityHigh {
		t.Errorf("py severity = %q, want high (database_specific fallback)", py.Severity)
	}
	if py.Title != "First line of details." {
		t.Errorf("py title = %q, want first line of details", py.Title)
	}
}

func TestSeverityForGroupPrefersCVSS(t *testing.T) {
	// CVSS present -> used even when database_specific differs.
	pkg := models.PackageVulns{
		Vulnerabilities: []*osvschema.Vulnerability{
			{Id: "GHSA-x", DatabaseSpecific: dbSpecificSeverity(t, "LOW")},
		},
	}
	group := models.GroupInfo{IDs: []string{"GHSA-x"}, MaxSeverity: "9.5"}
	if got := severityForGroup(group, pkg); got != SeverityCritical {
		t.Errorf("severityForGroup = %q, want critical from CVSS", got)
	}
}

func TestScanLockfilesEmpty(t *testing.T) {
	findings, err := scanLockfiles(nil)
	if err != nil {
		t.Fatalf("scanLockfiles(nil) error: %v", err)
	}
	if findings != nil {
		t.Errorf("scanLockfiles(nil) = %v, want nil", findings)
	}
}
