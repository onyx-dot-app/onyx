//go:build !windows

package devstack

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

type fakeCompose struct {
	projects []string
}

func (c *fakeCompose) down(_ context.Context, project string, _ bool) error {
	c.projects = append(c.projects, project)
	return nil
}

func discoverWith(containers []docker.ComposeContainer) DiscoverOptions {
	return DiscoverOptions{ListContainers: func() ([]docker.ComposeContainer, error) { return containers, nil }}
}

// isolatedLinkedStack starts an isolated stack in a linked worktree.
func isolatedLinkedStack(t *testing.T, project string) (*Stack, ServiceRecord) {
	t.Helper()
	a, b := sharedPair(t)
	stack, err := Open(b.Root, project, Isolated)
	if err != nil {
		t.Fatal(err)
	}
	stack.Registry = a.Registry
	t.Cleanup(func() { _ = stack.stopServices(testOptions().StopTimeout) })
	mustUp(t, stack, &fakeProvider{services: []string{"api"}})
	return stack, servicePID(t, stack, "api")
}

func TestDownProjectStopsOrphanedStackAndReleasesLeases(t *testing.T) {
	stack, api := isolatedLinkedStack(t, "orphan-data")
	containers := onyxContainers(stack.Project, stack.Root, true, time.Now())
	if err := os.RemoveAll(stack.Root); err != nil {
		t.Fatal(err)
	}
	inv := Discover(stack.Registry, discoverWith(containers))
	row := rowFor(t, inv, stack.Project)
	if row.Status != StatusOrphaned || row.StateDir != stack.StateDir || row.LeaseRoot != stack.Root {
		t.Fatalf("deleted worktree is not an orphan: %+v", row)
	}

	compose := &fakeCompose{}
	result, err := DownProject(context.Background(), stack.Registry, stack.Project, compose.down,
		ProjectOptions{StopTimeout: testOptions().StopTimeout, LockWait: time.Second, Discover: discoverWith(containers)})
	if err != nil {
		t.Fatal(err)
	}
	if isCurrent(api) || result.StoppedServices != 1 {
		t.Fatalf("orphaned service still runs: %+v", result)
	}
	if len(compose.projects) != 1 || compose.projects[0] != stack.Project {
		t.Fatalf("compose down calls = %v", compose.projects)
	}
	if got := leaseNames(t, stack.Registry, stack.Root); len(got) != 0 || result.ReleasedLeases == 0 {
		t.Fatalf("orphan leases were not released: %v %+v", got, result)
	}
	if _, err := os.Stat(ownerPath(stack.Registry, stack.Project)); !os.IsNotExist(err) || !result.RemovedOwner {
		t.Fatalf("orphan owner record remains: %v", err)
	}
}

func TestDownProjectRefusesLiveWorktreeWithoutForce(t *testing.T) {
	stack, api := isolatedLinkedStack(t, "live-data")
	compose := &fakeCompose{}
	opts := ProjectOptions{StopTimeout: testOptions().StopTimeout, LockWait: time.Second, Discover: discoverWith(nil)}
	if _, err := DownProject(context.Background(), stack.Registry, stack.Project, compose.down, opts); err == nil || !strings.Contains(err.Error(), "--force") {
		t.Fatalf("down --project stopped a live worktree's stack: %v", err)
	}
	if !isCurrent(api) || len(compose.projects) != 0 {
		t.Fatal("refused down changed the stack")
	}
	opts.Force = true
	if _, err := DownProject(context.Background(), stack.Registry, stack.Project, compose.down, opts); err != nil {
		t.Fatal(err)
	}
	if isCurrent(api) || len(compose.projects) != 1 {
		t.Fatal("forced down did not stop the stack")
	}
	if _, err := os.Stat(ownerPath(stack.Registry, stack.Project)); err != nil {
		t.Fatalf("down of a live worktree's stack removed its owner record: %v", err)
	}
}

func TestStopProjectKeepsInfrastructure(t *testing.T) {
	stack, api := isolatedLinkedStack(t, "stop-data")
	if err := os.RemoveAll(stack.Root); err != nil {
		t.Fatal(err)
	}
	if _, err := StopProject(context.Background(), stack.Registry, stack.Project, ProjectOptions{StopTimeout: testOptions().StopTimeout, LockWait: time.Second, Discover: discoverWith(nil)}); err != nil {
		t.Fatal(err)
	}
	if isCurrent(api) {
		t.Fatal("stop --project left the service running")
	}
	if _, err := os.Stat(filepath.Join(stack.StateDir, stateFileName)); err != nil {
		t.Fatal(err)
	}
}

func TestFindProjectRejectsUnknownProject(t *testing.T) {
	if _, err := FindProject(&Registry{Dir: t.TempDir()}, "nothing-here", discoverWith(nil)); err == nil {
		t.Fatal("found a stack that does not exist")
	}
}

func TestCleanupRowKeepsContainersOfAnotherOwner(t *testing.T) {
	stack, _ := isolatedLinkedStack(t, "shared-data")
	secondary := StackRow{Project: stack.Project, Mode: Isolated, StateDir: t.TempDir(), Status: StatusOrphaned}
	compose := &fakeCompose{}
	result, err := CleanupRow(context.Background(), stack.Registry, secondary, compose.down, ProjectOptions{LockWait: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	if len(compose.projects) != 0 || result.ComposeDown {
		t.Fatal("a secondary state stopped the owner's containers")
	}
	if _, err := os.Stat(ownerPath(stack.Registry, stack.Project)); err != nil {
		t.Fatalf("a secondary state removed the owner record: %v", err)
	}
}
