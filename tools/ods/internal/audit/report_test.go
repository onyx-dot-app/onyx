package audit

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func sampleResult() *Result {
	return &Result{
		Findings: []Finding{
			{ID: "GHSA-crit", Ecosystem: "npm", Package: "a", Version: "1.0.0", Severity: SeverityCritical, Title: "crit", URL: "https://osv.dev/vulnerability/GHSA-crit", Source: SourceOSV, Manifest: "web/bun.lock", FixedIn: "1.1.0"},
			{ID: "GHSA-mod", Ecosystem: "PyPI", Package: "b", Version: "2.0.0", Severity: SeverityModerate, Title: "mod", Source: SourceDependabot, Manifest: "pyproject.toml"},
			{ID: "GHSA-low", Ecosystem: "npm", Package: "c", Severity: SeverityLow, Title: "low", Source: SourceOSV},
		},
		Ignored:  []Finding{{ID: "GHSA-ign", Severity: SeverityHigh}},
		Blocking: []Finding{{ID: "GHSA-crit", Severity: SeverityCritical}},
	}
}

func TestRenderSARIF(t *testing.T) {
	var buf bytes.Buffer
	if err := renderSARIF(&buf, sampleResult()); err != nil {
		t.Fatalf("renderSARIF: %v", err)
	}

	var doc map[string]any
	if err := json.Unmarshal(buf.Bytes(), &doc); err != nil {
		t.Fatalf("output is not valid JSON: %v", err)
	}

	if doc["version"] != "2.1.0" {
		t.Errorf("version = %v", doc["version"])
	}

	runs := doc["runs"].([]any)
	if len(runs) != 1 {
		t.Fatalf("want exactly one run, got %d", len(runs))
	}
	run := runs[0].(map[string]any)

	driver := run["tool"].(map[string]any)["driver"].(map[string]any)
	if driver["name"] != "ods-audit" {
		t.Errorf("driver name = %v", driver["name"])
	}

	results := run["results"].([]any)
	if len(results) != 3 {
		t.Fatalf("want 3 results, got %d", len(results))
	}

	// Critical -> error, moderate -> warning, low -> note.
	levels := map[string]string{}
	for _, r := range results {
		rm := r.(map[string]any)
		levels[rm["ruleId"].(string)] = rm["level"].(string)
	}
	if levels["GHSA-crit"] != "error" {
		t.Errorf("crit level = %q, want error", levels["GHSA-crit"])
	}
	if levels["GHSA-mod"] != "warning" {
		t.Errorf("mod level = %q, want warning", levels["GHSA-mod"])
	}
	if levels["GHSA-low"] != "note" {
		t.Errorf("low level = %q, want note", levels["GHSA-low"])
	}

	// Location present when manifest is set.
	for _, r := range results {
		rm := r.(map[string]any)
		if rm["ruleId"] == "GHSA-crit" {
			locs := rm["locations"].([]any)
			uri := locs[0].(map[string]any)["physicalLocation"].(map[string]any)["artifactLocation"].(map[string]any)["uri"]
			if uri != "web/bun.lock" {
				t.Errorf("crit location uri = %v", uri)
			}
		}
	}
}

func TestRenderText(t *testing.T) {
	var buf bytes.Buffer
	if err := renderText(&buf, sampleResult()); err != nil {
		t.Fatalf("renderText: %v", err)
	}
	out := buf.String()
	if !strings.Contains(out, "GHSA-crit") {
		t.Error("text output missing finding id")
	}
	if !strings.Contains(out, "1 suppressed by allowlist") {
		t.Errorf("text output missing suppressed count:\n%s", out)
	}
	if !strings.Contains(out, "[dependabot]") {
		t.Error("text output should tag dependabot-sourced findings")
	}
}

func TestRenderTextNoFindings(t *testing.T) {
	var buf bytes.Buffer
	if err := renderText(&buf, &Result{}); err != nil {
		t.Fatalf("renderText: %v", err)
	}
	if !strings.Contains(buf.String(), "No dependency vulnerabilities found") {
		t.Errorf("unexpected empty output: %q", buf.String())
	}
}

func TestRenderUnknownFormat(t *testing.T) {
	var buf bytes.Buffer
	if err := render(&buf, "xml", sampleResult()); err == nil {
		t.Error("render should reject unknown format")
	}
}

func TestParseFormats(t *testing.T) {
	cases := map[string][]string{
		"":                {"text"},
		"   ":             {"text"},
		"sarif":           {"sarif"},
		"SARIF, Text":     {"sarif", "text"},
		"text,sarif,text": {"text", "sarif"}, // de-duped, order preserved
		",json,":          {"json"},
	}
	for in, want := range cases {
		got := parseFormats(in)
		if strings.Join(got, ",") != strings.Join(want, ",") {
			t.Errorf("parseFormats(%q) = %v, want %v", in, got, want)
		}
	}
}

// TestRenderReportRouting is the core of the CI use case: a combined
// sarif,text run must put valid SARIF on stdout (redirected to a file) and the
// human report on stderr (visible in the log), never mixing the two.
func TestRenderReportRouting(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if err := renderReport(&stdout, &stderr, "sarif,text", sampleResult()); err != nil {
		t.Fatalf("renderReport: %v", err)
	}

	// stdout is pure SARIF.
	var doc map[string]any
	if err := json.Unmarshal(stdout.Bytes(), &doc); err != nil {
		t.Fatalf("stdout is not valid SARIF JSON: %v\n%s", err, stdout.String())
	}
	if strings.Contains(stdout.String(), "Dependency vulnerabilities:") {
		t.Error("text report leaked into the SARIF stdout stream")
	}

	// stderr is the text report, and JSON must not have leaked into it.
	if !strings.Contains(stderr.String(), "GHSA-crit") {
		t.Errorf("stderr missing text report:\n%s", stderr.String())
	}
	if strings.Contains(stderr.String(), "\"$schema\"") {
		t.Error("SARIF leaked into the text stderr stream")
	}
}

func TestRenderReportLoneTextGoesToStdout(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if err := renderReport(&stdout, &stderr, "text", sampleResult()); err != nil {
		t.Fatalf("renderReport: %v", err)
	}
	if !strings.Contains(stdout.String(), "GHSA-crit") {
		t.Errorf("lone text should render to stdout, got stdout=%q", stdout.String())
	}
	if stderr.Len() != 0 {
		t.Errorf("lone text should not write to stderr, got %q", stderr.String())
	}
}

func TestRenderReportRejectsTwoDataFormats(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if err := renderReport(&stdout, &stderr, "json,sarif", sampleResult()); err == nil {
		t.Error("renderReport should reject two machine-readable formats")
	}
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Error("nothing should be written when the format set is rejected")
	}
}

func TestRenderReportRejectsUnknownFormat(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if err := renderReport(&stdout, &stderr, "sarif,xml", sampleResult()); err == nil {
		t.Error("renderReport should reject an unknown format")
	}
	// Validation happens before any writing, so a valid format alongside the bad
	// one must not produce partial output.
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Errorf("no output expected on bad format set; stdout=%q stderr=%q", stdout.String(), stderr.String())
	}
}

func TestRunbookShownOnlyWhenBlocking(t *testing.T) {
	// A realistic blocking finding carries an ecosystem (blockingFindings copies
	// the full finding), which the runbook threads into the example command.
	blocking := Finding{ID: "GHSA-crit", Ecosystem: "npm", Package: "a", Version: "1.0.0", Severity: SeverityCritical}
	res := &Result{Findings: []Finding{blocking}, Blocking: []Finding{blocking}}

	var withBlocking bytes.Buffer
	if err := renderText(&withBlocking, res); err != nil {
		t.Fatalf("renderText: %v", err)
	}
	out := withBlocking.String()
	if !strings.Contains(out, "ods audit ignore add GHSA-crit") {
		t.Errorf("runbook should print a ready-to-fill ignore command:\n%s", out)
	}
	if !strings.Contains(out, "--ecosystem \"npm\"") {
		t.Errorf("runbook command should carry the finding's ecosystem:\n%s", out)
	}
	if !strings.Contains(out, "Action required") {
		t.Errorf("runbook header missing:\n%s", out)
	}

	// No blocking findings -> no runbook.
	nonBlocking := &Result{Findings: []Finding{{ID: "GHSA-low", Severity: SeverityLow, Ecosystem: "npm", Package: "c"}}}
	var buf bytes.Buffer
	if err := renderText(&buf, nonBlocking); err != nil {
		t.Fatalf("renderText: %v", err)
	}
	if strings.Contains(buf.String(), "Action required") {
		t.Errorf("runbook should not appear without blocking findings:\n%s", buf.String())
	}
}

func TestBlockingFindings(t *testing.T) {
	findings := []Finding{
		{ID: "c", Severity: SeverityCritical},
		{ID: "h", Severity: SeverityHigh},
		{ID: "m", Severity: SeverityModerate},
		{ID: "l", Severity: SeverityLow},
	}

	if got := blockingFindings(findings, SeverityCritical); len(got) != 1 || got[0].ID != "c" {
		t.Errorf("fail-on=critical blocked %v, want [c]", idSet(got))
	}
	if got := blockingFindings(findings, SeverityHigh); len(got) != 2 {
		t.Errorf("fail-on=high blocked %d, want 2", len(got))
	}
	if got := blockingFindings(findings, SeverityLow); len(got) != 4 {
		t.Errorf("fail-on=low blocked %d, want 4", len(got))
	}
}

func TestDedupeFindings(t *testing.T) {
	in := []Finding{
		{ID: "GHSA-x", Ecosystem: "npm", Package: "a", Version: "1.0.0"},
		{ID: "GHSA-x", Ecosystem: "npm", Package: "a", Version: "1.0.0"}, // dup (e.g. root + web bun.lock)
		{ID: "GHSA-x", Ecosystem: "npm", Package: "a", Version: "1.0.1"}, // different version -> kept
		{ID: "ghsa-x", Ecosystem: "NPM", Package: "a", Version: "1.0.0"}, // case-insensitive dup
	}
	out := dedupeFindings(in)
	if len(out) != 2 {
		t.Errorf("dedupeFindings kept %d, want 2", len(out))
	}
}
