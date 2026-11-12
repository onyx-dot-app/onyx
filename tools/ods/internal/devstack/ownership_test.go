//go:build !windows

package devstack

import (
	"context"
	"strings"
	"testing"
)

func TestIsolatedProjectCannotBeClaimedByAnotherWorktree(t *testing.T) {
	a, b := sharedPair(t)
	first, err := Open(a.Root, "same-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Open(b.Root, "same-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	first.Registry, second.Registry = a.Registry, a.Registry
	t.Cleanup(func() {
		_ = first.stopServices(testOptions().StopTimeout)
		_ = second.stopServices(testOptions().StopTimeout)
	})
	mustUp(t, first, &fakeProvider{services: []string{"api"}})
	api := servicePID(t, first, "api")
	provider := &fakeProvider{services: []string{"api"}}
	_, err = second.Up(context.Background(), provider, testOptions())
	if err == nil || !strings.Contains(err.Error(), "owned") {
		t.Fatalf("another worktree claimed active project: %v", err)
	}
	if provider.composeUp != 0 || len(provider.migrated) != 0 || !isCurrent(api) {
		t.Fatal("conflicting startup touched existing deployment")
	}
}

func TestIsolatedProjectOwnerSurvivesLifecycleUnlock(t *testing.T) {
	a, b := sharedPair(t)
	first, err := Open(a.Root, "same-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Open(b.Root, "same-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	first.Registry, second.Registry = a.Registry, a.Registry
	if err := second.WriteState(&State{Phase: PhaseStopped}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = first.stopServices(testOptions().StopTimeout) })
	mustUp(t, first, &fakeProvider{services: []string{"api"}})
	if err := second.Down(context.Background(), &fakeProvider{}, testOptions()); err == nil {
		t.Fatal("older isolated state stopped another worktree's project")
	}
}

func TestIsolatedProjectOwnershipAppliesAcrossRepositories(t *testing.T) {
	registry := t.TempDir()
	first := newTestStack(t, registry)
	second := newTestStack(t, registry)
	first.Project, second.Project = "same-data", "same-data"
	mustUp(t, first, &fakeProvider{services: []string{"api"}})
	provider := &fakeProvider{services: []string{"api"}}
	if _, err := second.Up(context.Background(), provider, testOptions()); err == nil || !strings.Contains(err.Error(), "owned") {
		t.Fatalf("another repository claimed the same infrastructure: %v", err)
	}
	if provider.composeUp != 0 || len(provider.migrated) != 0 {
		t.Fatal("conflicting repository changed infrastructure")
	}
}

func TestSharedCanAdoptStoppedDurableIsolatedOwner(t *testing.T) {
	shared, caller := sharedPair(t)
	legacy, err := Open(shared.Root, "existing-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	legacy.Registry = shared.Registry
	t.Cleanup(func() { _ = legacy.stopServices(testOptions().StopTimeout) })
	mustUp(t, legacy, &fakeProvider{services: []string{"api"}})
	if err := legacy.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}
	next, err := Open(caller.Root, legacy.Project, Shared)
	if err != nil {
		t.Fatal(err)
	}
	next.Registry = shared.Registry
	mustUp(t, next, &fakeProvider{services: []string{"api"}})
	if release, err := legacy.LockInfrastructure(context.Background(), testOptions().LockWait); err == nil {
		release()
		t.Fatal("old isolated owner took back adopted shared infrastructure")
	}
}
