package audit

import (
	"encoding/json"
	"slices"
	"strings"
	"testing"
)

func TestNodeRuntimeReport(t *testing.T) {
	advisories := map[string]nodeAdvisory{
		"1": {CVEs: []string{"CVE-2099-12345"}, Vulnerable: "22.x || 24.x", Patched: "^22.23.5 || ^24.22.1", Severity: "critical", Platforms: []string{"linux"}},
		"2": {Vulnerable: "24.x", Patched: "^24.23.0", Severity: "high", Platforms: []string{"win32"}},
	}
	releases := []nodeRelease{{"v24.16.0", false}, {"v24.22.1", false}, {"v24.22.3", true}, {"v26.13.1", true}, {"v24.22.4", false}}
	for _, tc := range []struct {
		version string
		want    int
	}{{"v24.16.0", 4}, {"v24.22.1", 2}, {"v24.22.3", 0}, {"v24.22.4", 0}} {
		result, err := nodeRuntimeReport([]nodeRuntime{{nodeImagePin{"node@fixture", []string{"web/Dockerfile", "release.yml"}}, tc.version}}, advisories, releases)
		if err != nil || len(result.Blocking) != tc.want || len(result.ScannedPackages) != 1 {
			t.Fatalf("%s: got %+v, %v", tc.version, result, err)
		}
		for _, f := range result.Blocking {
			if f.ID == "CVE-2099-12345" && f.FixedIn != "24.22.1" {
				t.Fatalf("got fixed version %q, want 24.22.1", f.FixedIn)
			}
		}
	}
	runtimes := []nodeRuntime{{nodeImagePin{"node@fixture", []string{"web/Dockerfile"}}, "v24.22.3"}}
	if _, err := nodeRuntimeReport(runtimes, nil, releases); err == nil {
		t.Fatal("accepted missing advisories")
	}
	if _, err := nodeRuntimeReport(runtimes, advisories, []nodeRelease{{"v26.13.1", true}}); err == nil {
		t.Fatal("accepted unknown runtime version")
	}
}

func TestNodeGroupedCVEsRemainIndependent(t *testing.T) {
	const feed = `{"62":{"cve":["CVE-2019-9511","CVE-2019-9512"],"vulnerable":"24.x","patched":"^24.22.3","overview":"Two distinct flaws","severity":"high"}}`
	var advisories map[string]nodeAdvisory
	if err := json.Unmarshal([]byte(feed), &advisories); err != nil {
		t.Fatal(err)
	}
	result, err := nodeRuntimeReport([]nodeRuntime{{nodeImagePin{"node@fixture", []string{"release.yml"}}, "v24.16.0"}}, advisories, []nodeRelease{{"v24.16.0", true}})
	if err != nil {
		t.Fatal(err)
	}
	ids := []string{}
	for _, f := range result.Blocking {
		if len(f.Aliases) > 0 || f.Title != "Two distinct flaws" {
			t.Fatalf("unexpected advisory %+v", f)
		}
		ids = append(ids, f.ID)
	}
	if !slices.Equal(ids, []string{"CVE-2019-9511", "CVE-2019-9512"}) {
		t.Fatalf("got %v", ids)
	}
}

func TestNodeTrackingReportsEveryFixAndSeparatesReleasePolicy(t *testing.T) {
	pins := []nodeRuntime{{nodeImagePin{"a", []string{"one"}}, "v22.0.0"}, {nodeImagePin{"b", []string{"two"}}, "v24.0.0"}}
	releases := []nodeRelease{{"v22.0.0", false}, {"v22.23.5", true}, {"v24.0.0", false}, {"v24.22.3", true}}
	advisories := map[string]nodeAdvisory{"1": {CVEs: []string{"CVE-2099-12345"}, Vulnerable: "22.x || 24.x", Patched: "^22.23.5 || ^24.22.3", Severity: "high"}}
	report, err := nodeRuntimeReport(pins, advisories, releases)
	if err != nil {
		t.Fatal(err)
	}
	alerts := groupAlerts(report.Blocking, report.Findings, "main")
	if len(alerts) != 1 {
		t.Fatalf("got alerts %+v", alerts)
	}
	body := renderAlertBody(alerts[0])
	if !strings.Contains(body, "22.23.5, 24.22.3") || !strings.Contains(body, "blocking security release requirement") {
		t.Fatalf("issue: %s", body)
	}
	plan := PlanAnnouncement(AnnounceOptions{Failing: alerts, Branch: "main"})
	if plan.Post == nil || !strings.Contains(plan.Post.Text, "1 high CVE, security release requirements: 2") {
		t.Fatalf("post: %+v", plan.Post)
	}
}
