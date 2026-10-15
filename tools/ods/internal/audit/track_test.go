package audit

import (
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func scanAlert(category, rule, state, severity string, created time.Time) CodeScanningAlert {
	var a CodeScanningAlert
	a.MostRecentInstance.Category = category
	a.Rule.ID = rule
	a.Rule.SecuritySeverityLevel = severity
	a.State = state
	a.CreatedAt = created
	return a
}

func TestBuildSnapshot_countsCVEsPerImageAndFlagsOld(t *testing.T) {
	now := time.Date(2026, 10, 15, 12, 0, 0, 0, time.UTC)
	old := now.AddDate(0, 0, -120)
	recent := now.AddDate(0, 0, -3)
	snap := BuildSnapshot([]CodeScanningAlert{
		scanAlert("image-audit-sandbox", "CVE-1", "open", "critical", recent),
		// Two alerts of one rule are one CVE, open since the earlier.
		scanAlert("image-audit-sandbox", "CVE-2", "open", "high", recent),
		scanAlert("image-audit-sandbox", "CVE-2", "open", "high", old),
		scanAlert("image-audit-sandbox", "CVE-3", "fixed", "high", old),
		scanAlert("image-audit-sandbox", "CVE-4", "dismissed", "", old),
		scanAlert("image-audit-web", "CVE-1", "fixed", "critical", recent),
		// Not an image audit.
		scanAlert("ods-audit", "CVE-9", "open", "critical", old),
	}, now)

	if snap.Date != "2026-10-15" {
		t.Errorf("date %q", snap.Date)
	}
	sandbox := snap.Images["sandbox"]
	if sandbox.Total != 4 || sandbox.Open != 2 || sandbox.Resolved != 2 {
		t.Errorf("sandbox counts: %+v", sandbox)
	}
	if sandbox.OpenBySeverity["critical"] != 1 || sandbox.OpenBySeverity["high"] != 1 {
		t.Errorf("sandbox severities: %+v", sandbox.OpenBySeverity)
	}
	if len(sandbox.Flagged) != 1 || sandbox.Flagged[0] != (FlaggedCVE{ID: "CVE-2", Severity: "high", Opened: "2026-06-17", DaysOpen: 120}) {
		t.Errorf("flagged: %+v", sandbox.Flagged)
	}
	if web := snap.Images["web"]; web.Total != 1 || web.Open != 0 || web.Resolved != 1 || web.Flagged != nil {
		t.Errorf("web: %+v", web)
	}
	if len(snap.Images) != 2 {
		t.Errorf("images: %v", snap.Images)
	}
}

func TestHistory_recordReplacesTheSameDayAndRoundTrips(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.json")
	h, err := ReadHistory(path)
	if err != nil || len(h.Snapshots) != 0 {
		t.Fatalf("missing file: %+v, %v", h, err)
	}
	h.Record(Snapshot{Date: "2026-10-15", Images: map[string]ImageSnapshot{"web": {Total: 1}}})
	h.Record(Snapshot{Date: "2026-10-01"})
	h.Record(Snapshot{Date: "2026-10-15", Images: map[string]ImageSnapshot{"web": {Total: 2}}})
	if err := WriteHistory(path, h); err != nil {
		t.Fatal(err)
	}
	got, err := ReadHistory(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Snapshots) != 2 || got.Snapshots[0].Date != "2026-10-01" || got.Snapshots[1].Images["web"].Total != 2 {
		t.Errorf("history: %+v", got)
	}
}

func TestRenderTrackSummary_ordersImagesAndComparesToAWeekAgo(t *testing.T) {
	h := History{Snapshots: []Snapshot{
		{Date: "2026-10-07", Images: map[string]ImageSnapshot{"sandbox": {Open: 10}}},
		{Date: "2026-10-12", Images: map[string]ImageSnapshot{"sandbox": {Open: 1}}},
		{Date: "2026-10-15", Images: map[string]ImageSnapshot{
			"web":     {Total: 3, Open: 1, Resolved: 2, OpenBySeverity: map[string]int{"high": 1}},
			"sandbox": {Total: 20, Open: 12, Resolved: 8, OpenBySeverity: map[string]int{"high": 10, "critical": 2}, Flagged: []FlaggedCVE{{ID: "CVE-2", Severity: "high", Opened: "2026-06-17", DaysOpen: 120}}},
		}},
	}}
	got := RenderTrackSummary(h)
	want := "*📊 CVEs per image, 2026-10-15*\n" +
		"• *sandbox*: 12 open (2 critical, 10 high), 8 resolved, 20 total (+2 open since 2026-10-07)\n" +
		"• *web*: 1 open (1 high), 2 resolved, 3 total (+1 open since 2026-10-07)\n" +
		"*🚩 Open 90+ days:* 1\n" +
		"• `CVE-2` in *sandbox* (high): open 120 days, since 2026-06-17"
	if got != want {
		t.Errorf("got:\n%s\nwant:\n%s", got, want)
	}
	if got := RenderTrackSummary(History{Snapshots: h.Snapshots[2:]}); !strings.Contains(got, "12 open (2 critical, 10 high), 8 resolved, 20 total\n") {
		t.Errorf("no week-old snapshot:\n%s", got)
	}
}

func TestRenderTrackSummary_noFlaggedCVEs(t *testing.T) {
	got := RenderTrackSummary(History{Snapshots: []Snapshot{{Date: "2026-10-15", Images: map[string]ImageSnapshot{"web": {Total: 1, Resolved: 1}}}}})
	if !strings.HasSuffix(got, "*🚩 Open 90+ days:* none.") {
		t.Errorf("got:\n%s", got)
	}
}
