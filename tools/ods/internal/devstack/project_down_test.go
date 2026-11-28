//go:build !windows

package devstack

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

type fakeCompose struct {
	projects []string
	volumes  []bool
}

func (c *fakeCompose) down(_ context.Context, project string, volumes bool) error {
	c.projects = append(c.projects, project)
	c.volumes = append(c.volumes, volumes)
	return nil
}

func discoverWith(containers []docker.ComposeContainer) DiscoverOptions {
	return discoverWithVolumes(containers, nil)
}

func discoverWithVolumes(containers []docker.ComposeContainer, volumes map[string]int) DiscoverOptions {
	return DiscoverOptions{
		ListContainers: func() ([]docker.ComposeContainer, error) { return containers, nil },
		ListVolumes:    func() (map[string]int, error) { return volumes, nil },
	}
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

func TestStopProjectStopsServicesAndKeepsInfrastructure(t *testing.T) {
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
	if got := leaseNames(t, stack.Registry, stack.Root); got["api"] != 0 {
		t.Fatalf("stop --project kept application leases: %v", got)
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

func TestDownProjectRemovesOwnerRecordWithoutState(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	path := ownerPath(registry, "old-data")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"state_dir":"/missing/ods-stack"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	compose := &fakeCompose{}
	if _, err := DownProject(context.Background(), registry, "old-data", compose.down, ProjectOptions{LockWait: time.Second, Discover: discoverWith(nil)}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("owner record remains: %v", err)
	}
}

func TestOwnerWithoutStateKeepsItsVolumesUntilTheyAreDeleted(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	path := ownerPath(registry, "removed-1")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"state_dir":"/missing/ods-stack"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	discover := discoverWithVolumes(nil, map[string]int{"removed-1": 7, "unrelated": 2})
	row := rowFor(t, Discover(registry, discover), "removed-1")
	if row.Status != StatusOrphaned || row.Volumes != 7 || !row.OnlyVolumes() || row.Next != "ods stack prune --volumes" {
		t.Fatalf("owner without state: %+v", row)
	}

	compose := &fakeCompose{}
	opts := ProjectOptions{LockWait: time.Second, Discover: discover}
	if _, err := CleanupRow(context.Background(), registry, row, compose.down, opts); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("the owner record was removed while its volumes remain: %v", err)
	}

	// Compose exits 0 and keeps a volume that a container still uses.
	opts.Volumes = true
	result, err := CleanupRow(context.Background(), registry, row, compose.down, opts)
	if err == nil || !strings.Contains(err.Error(), "still uses") {
		t.Fatalf("an in-use volume did not fail the cleanup: %v", err)
	}
	if result.RemovedVolumes || result.RemovedOwner {
		t.Fatalf("an in-use volume counted as removed: %+v", result)
	}

	opts.Discover.ListVolumes = func() (map[string]int, error) { return nil, errors.New("docker volume ls failed") }
	result, err = CleanupRow(context.Background(), registry, row, compose.down, opts)
	if err == nil || result.RemovedOwner {
		t.Fatalf("a failed volume check was hidden: err %v, result %+v", err, result)
	}

	opts.Discover = discoverWithVolumes(nil, map[string]int{"unrelated": 2})
	result, err = CleanupRow(context.Background(), registry, row, compose.down, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(compose.projects) != 4 || compose.projects[3] != "removed-1" || !compose.volumes[3] || !result.RemovedVolumes || !result.RemovedOwner {
		t.Fatalf("volumes were not deleted: calls %v %v, result %+v", compose.projects, compose.volumes, result)
	}
}

func TestOwnerWithoutStateStaysWhenTheVolumesCannotBeListed(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	path := ownerPath(registry, "removed-1")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"state_dir":"/missing/ods-stack"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	discover := DiscoverOptions{
		ListContainers: func() ([]docker.ComposeContainer, error) { return nil, nil },
		ListVolumes:    func() (map[string]int, error) { return nil, errors.New("docker volume ls failed") },
	}
	var row StackRow
	for _, r := range Discover(registry, discover).Rows {
		if r.OwnerRecord == path {
			row = r
		}
	}
	if row.Status != StatusOrphaned {
		t.Fatalf("owner without state: %+v", row)
	}
	for _, volumes := range []bool{false, true} {
		opts := ProjectOptions{LockWait: time.Second, Discover: discover, Volumes: volumes}
		if _, err := CleanupRow(context.Background(), registry, row, (&fakeCompose{}).down, opts); err != nil {
			t.Fatal(err)
		}
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("volumes %v: the owner record was removed while its volumes are unknown: %v", volumes, err)
		}
	}
}

func TestCleanupRowRefusesWhenTheOwnerStateIsUnreadable(t *testing.T) {
	stack, _ := isolatedLinkedStack(t, "corrupt-owner")
	if err := os.WriteFile(filepath.Join(stack.StateDir, stateFileName), []byte("not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	secondary := StackRow{Project: stack.Project, Mode: Isolated, StateDir: t.TempDir(), Status: StatusOrphaned}
	compose := &fakeCompose{}
	if _, err := CleanupRow(context.Background(), stack.Registry, secondary, compose.down, ProjectOptions{LockWait: time.Second}); err == nil || !strings.Contains(err.Error(), "cannot be read") {
		t.Fatalf("err = %v", err)
	}
	if len(compose.projects) != 0 {
		t.Fatal("cleanup stopped containers of an unreadable owner")
	}
	if _, err := os.Stat(ownerPath(stack.Registry, stack.Project)); err != nil {
		t.Fatalf("owner record removed: %v", err)
	}
}

func TestCleanupRowRefusesWhenTheOwnerRecordIsUnreadable(t *testing.T) {
	stack, _ := isolatedLinkedStack(t, "corrupt-record")
	if err := os.WriteFile(ownerPath(stack.Registry, stack.Project), []byte("not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	secondary := StackRow{Project: stack.Project, Mode: Isolated, StateDir: t.TempDir(), Status: StatusOrphaned}
	compose := &fakeCompose{}
	if _, err := CleanupRow(context.Background(), stack.Registry, secondary, compose.down, ProjectOptions{LockWait: time.Second}); err == nil || len(compose.projects) != 0 {
		t.Fatalf("err = %v, compose = %v", err, compose.projects)
	}
}

func TestCleanupRowSkipsAnIdleStackRestartedAfterItWasListed(t *testing.T) {
	stack, _ := isolatedLinkedStack(t, "restarted-later")
	st, err := stack.ReadState()
	if err != nil || st == nil {
		t.Fatalf("state %v, %v", st, err)
	}
	row := StackRow{Project: stack.Project, Mode: Isolated, StateDir: stack.StateDir, Root: stack.Root, RootExists: true,
		Worktree: true, Status: StatusInfraOnly, Since: time.Now().Add(-48 * time.Hour)}
	compose := &fakeCompose{}
	opts := ProjectOptions{LockWait: time.Second, Force: true, IdleCutoff: time.Now().Add(-6 * time.Hour)}
	if _, err := CleanupRow(context.Background(), stack.Registry, row, compose.down, opts); !errors.Is(err, ErrNotIdle) {
		t.Fatalf("err = %v, want ErrNotIdle", err)
	}
	if len(compose.projects) != 0 {
		t.Fatalf("a restarted stack was stopped: %v", compose.projects)
	}
}
