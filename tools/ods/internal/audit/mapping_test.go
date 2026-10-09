package audit

import (
	"testing"

	"github.com/google/osv-scanner/v2/pkg/models"
	"github.com/ossf/osv-schema/bindings/go/osvschema"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestParseSeverity(t *testing.T) {
	cases := map[string]Severity{
		" CRITICAL ": SeverityCritical,
		"High":       SeverityHigh,
		"moderate":   SeverityModerate,
		"MEDIUM":     SeverityModerate,
		"low":        SeverityLow,
		"":           SeverityUnknown,
		"severe":     SeverityUnknown,
	}
	for in, want := range cases {
		if got := ParseSeverity(in); got != want {
			t.Errorf("ParseSeverity(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestSeverityAtLeast(t *testing.T) {
	order := []Severity{SeverityUnknown, SeverityLow, SeverityModerate, SeverityHigh, SeverityCritical}
	for i, s := range order {
		for j, other := range order {
			if got, want := s.AtLeast(other), i >= j; got != want {
				t.Errorf("%q.AtLeast(%q) = %v, want %v", s, other, got, want)
			}
		}
	}
}

func TestVulnTitle(t *testing.T) {
	cases := []struct {
		name string
		vuln *osvschema.Vulnerability
		want string
	}{
		{"summary wins", &osvschema.Vulnerability{Summary: " XSS ", Details: "details"}, "XSS"},
		{"first line of details", &osvschema.Vulnerability{Details: "  First.  \nSecond."}, "First."},
		{"single-line details", &osvschema.Vulnerability{Details: " Only line "}, "Only line"},
		{"nothing to show", &osvschema.Vulnerability{Details: "  "}, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := vulnTitle(tc.vuln); got != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, got)
			}
		})
	}
}

func TestSeverityForGroup_fallbacks(t *testing.T) {
	notALabel, err := structpb.NewStruct(map[string]any{"severity": 7})
	if err != nil {
		t.Fatal(err)
	}
	pkg := models.PackageVulns{
		Vulnerabilities: []*osvschema.Vulnerability{
			{Id: "GHSA-other", DatabaseSpecific: dbSpecificSeverity(t, "CRITICAL")},
			{Id: "GHSA-label", DatabaseSpecific: dbSpecificSeverity(t, "MODERATE")},
			{Id: "GHSA-none"},
			{Id: "GHSA-number", DatabaseSpecific: notALabel},
		},
	}
	cases := []struct {
		name  string
		group models.GroupInfo
		want  Severity
	}{
		{"unparseable score uses the label", models.GroupInfo{IDs: []string{"GHSA-label"}, MaxSeverity: "n/a"}, SeverityModerate},
		{"zero score uses the label", models.GroupInfo{IDs: []string{"GHSA-label"}, MaxSeverity: "0"}, SeverityModerate},
		{"no database_specific", models.GroupInfo{IDs: []string{"GHSA-none"}}, SeverityUnknown},
		{"non-string severity", models.GroupInfo{IDs: []string{"GHSA-number"}}, SeverityUnknown},
		{"no matching record", models.GroupInfo{IDs: []string{"GHSA-missing"}}, SeverityUnknown},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := severityForGroup(tc.group, pkg); got != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, got)
			}
		})
	}
}

func TestFindingsFromResults_groupWithoutIDs(t *testing.T) {
	res := models.VulnerabilityResults{Results: []models.PackageSource{{
		Packages: []models.PackageVulns{{
			Package: models.PackageInfo{Name: "lodash", Ecosystem: "npm"},
			Groups:  []models.GroupInfo{{}},
		}},
	}}}
	findings := findingsFromResults(res)
	if len(findings) != 1 {
		t.Fatalf("expected 1 finding, got %d", len(findings))
	}
	if f := findings[0]; f.ID != "" || f.Title != "" || f.Severity != SeverityUnknown {
		t.Fatalf("expected an empty id, title, and unknown severity, got %+v", f)
	}
}

func TestTruncate(t *testing.T) {
	cases := []struct {
		in   string
		n    int
		want string
	}{
		{"short", 10, "short"},
		{"exact", 5, "exact"},
		{"a long title", 6, "a lon…"},
		{"abc", 1, "a"},
		{"abc", 0, ""},
	}
	for _, tc := range cases {
		if got := truncate(tc.in, tc.n); got != tc.want {
			t.Errorf("truncate(%q, %d) = %q, want %q", tc.in, tc.n, got, tc.want)
		}
	}
}

func TestRuleDescription(t *testing.T) {
	if got := ruleDescription(Finding{ID: "GHSA-x", Package: "lodash", Title: "Prototype pollution"}); got != "Prototype pollution" {
		t.Errorf("expected the title, got %q", got)
	}
	if got := ruleDescription(Finding{ID: "GHSA-x", Package: "lodash"}); got != "GHSA-x affects lodash" {
		t.Errorf("expected a generated description, got %q", got)
	}
}

func TestSecuritySeverityScore(t *testing.T) {
	cases := map[Severity]string{
		SeverityCritical: "9.0",
		SeverityHigh:     "7.0",
		SeverityModerate: "4.0",
		SeverityLow:      "1.0",
		SeverityUnknown:  "0.0",
	}
	for sev, want := range cases {
		if got := securitySeverityScore(sev); got != want {
			t.Errorf("securitySeverityScore(%q) = %q, want %q", sev, got, want)
		}
	}
}
