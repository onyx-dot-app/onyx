package audit

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestUpdateDeadlinesSurviveRetriesAndNewReleases(t *testing.T) {
	now := time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC)
	policy, err := ObserveUpdate(PackageUpdates{}, "157.0.1.2", "157.0.1.1", now)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		version  string
		blocking bool
	}{{"157.0.1.1", false}, {"156.9.9.9", true}, {"157.0.1.2", false}} {
		status, err := CheckUpdate("example", tc.version, policy, now)
		if err != nil || status.Blocking != tc.blocking {
			t.Fatalf("immediate policy for %s: %+v %v", tc.version, status, err)
		}
	}
	for _, observation := range []struct {
		version string
		hours   int
	}{{"157.0.1.2", 12}, {"157.0.1.3", 23}} {
		policy, err = ObserveUpdate(policy, observation.version, "", now.Add(time.Duration(observation.hours)*time.Hour))
		if err != nil {
			t.Fatal(err)
		}
	}
	for _, tc := range []struct {
		hours             int
		warning, blocking bool
	}{{23, false, false}, {24, true, false}, {71, true, false}, {72, true, true}} {
		// Observation is healthy; warning must come from the original pending update.
		policy.CheckedAt = now.Add(time.Duration(tc.hours) * time.Hour)
		status, err := CheckUpdate("example", "157.0.1.1", policy, policy.CheckedAt)
		if err != nil {
			t.Fatal(err)
		}
		if status.Warning != tc.warning || status.Blocking != tc.blocking {
			t.Fatalf("hour %d: %+v", tc.hours, status)
		}
	}
	status, err := CheckUpdate("example", "157.0.1.3", policy, now.Add(96*time.Hour))
	if err != nil || status.Blocking || !status.Warning {
		t.Fatalf("stale observation must alert without blocking current pin: %+v %v", status, err)
	}
	status, err = CheckUpdate("example", "156.9.9.9", policy, now.Add(96*time.Hour))
	if err != nil || !status.Blocking {
		t.Fatalf("minimum: %+v %v", status, err)
	}
	if _, err := ObserveUpdate(policy, "157.0.1.3", "156.0.0.0", now.Add(96*time.Hour)); err == nil {
		t.Fatal("minimum decreased")
	}
	if _, err := ObserveUpdate(policy, "157.0.1.1", "", now.Add(96*time.Hour)); err == nil {
		t.Fatal("upstream rollback accepted")
	}
}

func TestInvalidUpdatePolicyFailsClosed(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	valid := PackageUpdates{CheckedAt: now, Minimum: "1", Releases: map[string]time.Time{"2": now}}
	for _, tc := range []struct {
		name             string
		policy           PackageUpdates
		version, minimum string
		at               time.Time
	}{
		{"invalid version", valid, "x", "", now},
		{"overflow", valid, "18446744073709551616", "", now},
		{"invalid minimum", valid, "2", "x", now},
		{"invalid previous minimum", PackageUpdates{Minimum: "bad"}, "2", "2", now},
		{"clock rollback", valid, "2", "", now.Add(-time.Second)},
		{"invalid release", PackageUpdates{Minimum: "1", CheckedAt: now, Releases: map[string]time.Time{"bad": now}}, "2", "", now},
		{"zero release time", PackageUpdates{Minimum: "1", CheckedAt: now, Releases: map[string]time.Time{"2": {}}}, "2", "", now},
		{"future release time", PackageUpdates{Minimum: "1", CheckedAt: now, Releases: map[string]time.Time{"2": now.Add(time.Second)}}, "2", "", now},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := ObserveUpdate(tc.policy, tc.version, tc.minimum, tc.at); err == nil {
				t.Fatal("accepted invalid observation")
			}
		})
	}
	for _, tc := range []struct {
		policy  PackageUpdates
		version string
	}{
		{PackageUpdates{}, "1"}, {PackageUpdates{CheckedAt: now.Add(time.Second), Releases: valid.Releases}, "1"},
		{valid, "bad"}, {PackageUpdates{CheckedAt: now, Minimum: "bad", Releases: valid.Releases}, "1"},
		{PackageUpdates{CheckedAt: now, Minimum: "1", Releases: map[string]time.Time{"bad": now}}, "1"},
		{PackageUpdates{CheckedAt: now, Minimum: "1", Releases: map[string]time.Time{"2": {}}}, "1"},
	} {
		if _, err := CheckUpdate("example", tc.version, tc.policy, now); err == nil {
			t.Fatalf("accepted invalid policy: %+v", tc)
		}
	}
	if cmp, err := compareNumericVersions("1.0.0", "1"); err != nil || cmp != 0 {
		t.Fatalf("numeric equality: %d %v", cmp, err)
	}
	if cmp, err := compareNumericVersions("1", "1.0.1"); err != nil || cmp != -1 {
		t.Fatalf("numeric order: %d %v", cmp, err)
	}
}

func TestReadUpdatePolicyStorageFailures(t *testing.T) {
	dir := t.TempDir()
	for _, data := range []string{"not json", "{}", "null"} {
		file := filepath.Join(dir, "policy.json")
		if err := os.WriteFile(file, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := ReadUpdatePolicy(file); err == nil {
			t.Fatalf("accepted %s", data)
		}
	}
	t.Setenv("TMPDIR", filepath.Join(dir, "missing"))
	if _, err := ReadUpdatePolicy("s3://bucket/policy.json"); err == nil {
		t.Fatal("missing temp directory passed")
	}
	t.Setenv("TMPDIR", dir)
	bin := fakeBinDir(t)
	writeFakeCommand(t, bin, "aws", "#!/bin/sh\nexit 1\n")
	if _, err := ReadUpdatePolicy("s3://bucket/policy.json"); err == nil {
		t.Fatal("failed storage read passed")
	}
	writeFakeCommand(t, bin, "aws", `#!/bin/sh
for arg in "$@"; do output="$arg"; done
printf '%s' '{"example":{"minimum":"1"}}' > "$output"
`)
	if policy, err := ReadUpdatePolicy("s3://bucket/policy.json"); err != nil || policy["example"].Minimum != "1" {
		t.Fatalf("read storage: %v %v", policy, err)
	}
}
