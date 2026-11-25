package audit

import "testing"

func TestNodeRuntimeReport(t *testing.T) {
	advisories := map[string]nodeAdvisory{
		"1": {CVEs: []string{"CVE-fixture"}, Vulnerable: "22.x || 24.x", Patched: "^22.23.5 || ^24.22.3", Severity: "critical", Platforms: []string{"linux"}},
		"2": {Vulnerable: "24.x", Patched: "^24.23.0", Severity: "high", Platforms: []string{"win32"}},
	}
	releases := []nodeRelease{{"v24.16.0", false}, {"v24.22.3", true}, {"v26.13.1", true}, {"v24.22.4", false}}
	for _, tc := range []struct {
		version string
		want    int
	}{{"v24.16.0", 4}, {"v24.22.3", 0}, {"v24.22.4", 0}} {
		result, err := nodeRuntimeReport([]NodeRuntime{{"node@fixture", tc.version, []string{"web/Dockerfile", "release.yml"}}}, advisories, releases)
		if err != nil || len(result.Blocking) != tc.want || len(result.ScannedPackages) != 1 {
			t.Fatalf("%s: got %+v, %v", tc.version, result, err)
		}
	}
	runtimes := []NodeRuntime{{"node@fixture", "v24.22.3", []string{"web/Dockerfile"}}}
	if _, err := nodeRuntimeReport(runtimes, nil, releases); err == nil {
		t.Fatal("accepted missing advisories")
	}
	if _, err := nodeRuntimeReport(runtimes, advisories, []nodeRelease{{"v26.13.1", true}}); err == nil {
		t.Fatal("accepted unknown runtime version")
	}
}
