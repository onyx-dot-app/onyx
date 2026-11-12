package audit

import (
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
