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
							{IDs: []string{"GHSA-aaaa", "GHSA-bbbb", "GHSA-cccc"}, Aliases: []string{"GHSA-aaaa", "CVE-2020-1"}, MaxSeverity: "9.8"},
						},
						Vulnerabilities: []*osvschema.Vulnerability{
							// The first record of the group names no range; the fix
							// comes from the second.
							{Id: "GHSA-aaaa", Summary: "Prototype pollution"},
							{
								Id: "GHSA-bbbb",
								// Two lines fixed, one below the install, one for another
								// package and one for another ecosystem; the lowest above
								// the install for this package is the pin.
								Affected: []*osvschema.Affected{
									{
										Package: &osvschema.Package{Name: "lodash", Ecosystem: "npm"},
										Ranges: []*osvschema.Range{
											{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "3.10.2"}}},
											{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "5.0.0"}, {Fixed: "5.0.1"}}},
											{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "4.0.0"}, {Fixed: "4.17.21"}}},
										},
									},
									{
										Package: &osvschema.Package{Name: "lodash-es", Ecosystem: "npm"},
										Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "4.17.1"}}}},
									},
									{
										Package: &osvschema.Package{Name: "lodash", Ecosystem: "PyPI"},
										Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "4.17.5"}}}},
									},
								},
							},
							// A third record fixed later: every record needs its fix, so
							// the group's version is the highest.
							{
								Id: "GHSA-cccc",
								Affected: []*osvschema.Affected{{
									Package: &osvschema.Package{Name: "lodash", Ecosystem: "npm"},
									Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "4.18.0"}}}},
								}},
							},
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
	if npm.FixedIn != "4.18.0" {
		t.Errorf("npm fixed_in = %q, want the highest of each record's lowest fix above 4.17.0", npm.FixedIn)
	}

	py := findings[1]
	if py.Severity != SeverityHigh {
		t.Errorf("py severity = %q, want high (database_specific fallback)", py.Severity)
	}
	if py.FixedIn != "" {
		t.Errorf("py fixed_in = %q, want none without affected ranges", py.FixedIn)
	}
	if py.Title != "First line of details." {
		t.Errorf("py title = %q, want first line of details", py.Title)
	}
}

func TestFixedFor_skipsVersionsAnotherRecordStillLists(t *testing.T) {
	// The first advisory came back in 3.0 and was fixed again in 4.0, so the
	// second advisory's 3.5 is no fix for the group.
	vulns := []*osvschema.Vulnerability{
		{Id: "GHSA-1", Affected: []*osvschema.Affected{{
			Package: &osvschema.Package{Name: "pkg", Ecosystem: "npm"},
			Ranges: []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{
				{Introduced: "0"}, {Fixed: "2.0.0"}, {Introduced: "3.0.0"}, {Fixed: "4.0.0"},
			}}},
		}}},
		{Id: "GHSA-2", Affected: []*osvschema.Affected{{
			Package: &osvschema.Package{Name: "pkg", Ecosystem: "npm"},
			Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "3.5.0"}}}},
		}}},
		// An interval closed by last_affected below the install.
		{Id: "GHSA-3", Affected: []*osvschema.Affected{{
			Package: &osvschema.Package{Name: "pkg", Ecosystem: "npm"},
			Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0.5.0"}, {LastAffected: "0.9.0"}}}},
		}}},
	}
	pkg := models.PackageInfo{Name: "pkg", Version: "1.0.0", Ecosystem: "npm"}
	if got := fixedFor(vulns, []string{"GHSA-1", "GHSA-2", "GHSA-3"}, pkg); got != "4.0.0" {
		t.Fatalf("fixedFor = %q, want 4.0.0, the lowest fix no record still lists as affected", got)
	}
	if got := fixedFor(vulns, []string{"GHSA-1", "GHSA-2", "GHSA-3"}, models.PackageInfo{Name: "pkg", Version: "1.0.0", Ecosystem: "Nope"}); got != "" {
		t.Fatalf("fixedFor = %q, want none for an ecosystem the comparator cannot place", got)
	}
	// A record that lists 4.0.0 among its affected versions rules it out too.
	vulns = append(vulns, &osvschema.Vulnerability{Id: "GHSA-5", Affected: []*osvschema.Affected{{
		Package:  &osvschema.Package{Name: "pkg", Ecosystem: "npm"},
		Versions: []string{"1.0.0", "4.0.0"},
	}}})
	if got := fixedFor(vulns, []string{"GHSA-1", "GHSA-2", "GHSA-3", "GHSA-5"}, pkg); got != "" {
		t.Fatalf("fixedFor = %q, want none once a record lists the only candidate as affected", got)
	}
	// A range still open at the candidate keeps it affected.
	open := []*osvschema.Vulnerability{{Id: "GHSA-4", Affected: []*osvschema.Affected{{
		Package: &osvschema.Package{Name: "pkg", Ecosystem: "npm"},
		Ranges: []*osvschema.Range{
			{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "2.0.0"}}},
			{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "1.5.0"}}},
		},
	}}}}
	if got := fixedFor(open, []string{"GHSA-4"}, pkg); got != "" {
		t.Fatalf("fixedFor = %q, want none while a range stays open past every fix", got)
	}
	// A limit caps a range, so a fix past it stands; "*" caps nothing.
	limited := func(limit string) []*osvschema.Vulnerability {
		return []*osvschema.Vulnerability{
			{Id: "GHSA-6", Affected: []*osvschema.Affected{{
				Package: &osvschema.Package{Name: "pkg", Ecosystem: "npm"},
				Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Limit: limit}}}},
			}}},
			{Id: "GHSA-7", Affected: []*osvschema.Affected{{
				Package: &osvschema.Package{Name: "pkg", Ecosystem: "npm"},
				Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "2.1.0"}}}},
			}}},
		}
	}
	if got := fixedFor(limited("2.0.0"), []string{"GHSA-6", "GHSA-7"}, pkg); got != "2.1.0" {
		t.Fatalf("fixedFor = %q, want 2.1.0, past the other range's limit", got)
	}
	if got := fixedFor(limited("*"), []string{"GHSA-6", "GHSA-7"}, pkg); got != "" {
		t.Fatalf("fixedFor = %q, want none under an unbounded limit", got)
	}
}

func TestFixedFor_keepsDistributionReleasesApart(t *testing.T) {
	// Debian:12 fixed the package in 1.5; Debian:13 has only an open range,
	// so the Debian:13 install has no fix, and a bare "Debian" entry counts
	// for either release.
	vulns := []*osvschema.Vulnerability{{Id: "DEBIAN-CVE-1", Affected: []*osvschema.Affected{
		{
			Package: &osvschema.Package{Name: "pkg", Ecosystem: "Debian:12"},
			Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "1.5"}}}},
		},
		{
			Package: &osvschema.Package{Name: "pkg", Ecosystem: "Debian:13"},
			Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}}}},
		},
	}}}
	if got := fixedFor(vulns, []string{"DEBIAN-CVE-1"}, models.PackageInfo{Name: "pkg", Version: "1.0", Ecosystem: "Debian:13"}); got != "" {
		t.Fatalf("fixedFor = %q, want none for Debian:13 from a Debian:12 fix", got)
	}
	if got := fixedFor(vulns, []string{"DEBIAN-CVE-1"}, models.PackageInfo{Name: "pkg", Version: "1.0", Ecosystem: "Debian:12"}); got != "1.5" {
		t.Fatalf("fixedFor = %q, want 1.5 for Debian:12", got)
	}
	bare := []*osvschema.Vulnerability{{Id: "DEBIAN-CVE-2", Affected: []*osvschema.Affected{{
		Package: &osvschema.Package{Name: "pkg", Ecosystem: "Debian"},
		Ranges:  []*osvschema.Range{{Type: osvschema.Range_ECOSYSTEM, Events: []*osvschema.Event{{Introduced: "0"}, {Fixed: "2.0"}}}},
	}}}}
	if got := fixedFor(bare, []string{"DEBIAN-CVE-2"}, models.PackageInfo{Name: "pkg", Version: "1.0", Ecosystem: "Debian:13"}); got != "2.0" {
		t.Fatalf("fixedFor = %q, want 2.0 from a release-less entry", got)
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
