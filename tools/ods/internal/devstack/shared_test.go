//go:build !windows

package devstack

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func linkedWorktree(t *testing.T, root string) string {
	t.Helper()
	gittest.Git(t, root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", "fixture")
	dir := filepath.Join(t.TempDir(), "linked")
	gittest.Git(t, root, "worktree", "add", "--detach", dir)
	return dir
}

func sharedPair(t *testing.T) (*Stack, *Stack) {
	t.Helper()
	registry := t.TempDir()
	fixture := newTestStack(t, registry)
	linked := linkedWorktree(t, fixture.Root)
	if err := os.MkdirAll(filepath.Join(linked, ".vscode"), 0o755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"env_template.txt", "env.web_template.txt"} {
		data, err := os.ReadFile(filepath.Join(fixture.Root, ".vscode", name))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(linked, ".vscode", name), data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	first, err := Open(fixture.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Open(linked, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	first.Registry = &Registry{Dir: registry}
	second.Registry = first.Registry
	t.Cleanup(func() {
		if err := first.stopServices(testOptions().StopTimeout); err != nil {
			t.Error(err)
		}
	})
	return first, second
}

func TestIsolatedWorktreesKeepTheirOwnDataAndState(t *testing.T) {
	a, b := sharedPair(t)
	first, err := Open(a.Root, "", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Open(b.Root, "", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if first.Project == second.Project || first.StateDir == second.StateDir || first.StateDir == a.StateDir {
		t.Fatal("isolated stacks share data or lifecycle state")
	}
}

type handoffProvider struct {
	*fakeProvider
	previous ServiceRecord
}

func (p *handoffProvider) Migrate(ctx context.Context, env []string) error {
	if isCurrent(p.previous) {
		return errors.New("previous checkout is still running during migration")
	}
	return p.fakeProvider.Migrate(ctx, env)
}

func TestSharedUpTransfersCheckoutBeforeMigrationsAndRetainsPorts(t *testing.T) {
	a, b := sharedPair(t)
	provider := &fakeProvider{services: []string{"web", "api"}, infra: []PortRequest{{Name: "POSTGRES_HOST_PORT", Preferred: testBasePort + 600}}}
	initial, err := a.Up(context.Background(), provider, testOptions())
	if err != nil {
		t.Fatal(err)
	}
	st, err := a.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	previous := st.Services[0]
	next, err := b.Up(context.Background(), &handoffProvider{fakeProvider: provider, previous: previous}, testOptions())
	if err != nil {
		t.Fatal(err)
	}
	if !next.Ready || next.Root != b.Root || !reflect.DeepEqual(initial.Ports, next.Ports) {
		t.Fatalf("handoff lost ownership or ports: %+v", next)
	}
	fromOld, err := a.Status()
	if err != nil || fromOld.Root != b.Root {
		t.Fatalf("status hid active checkout: %+v %v", fromOld, err)
	}
	again, err := b.Up(context.Background(), provider, testOptions())
	if err != nil || again.Services[0].PID != next.Services[0].PID {
		t.Fatalf("same owner restarted unchanged services: %+v %v", again, err)
	}
}

func TestForeignLifecycleCommandsCannotStopSharedOwner(t *testing.T) {
	for _, action := range []string{"start", "restart", "stop", "down"} {
		t.Run(action, func(t *testing.T) {
			a, b := sharedPair(t)
			p := &fakeProvider{services: []string{"web"}}
			initial, err := a.Up(context.Background(), p, testOptions())
			if err != nil {
				t.Fatal(err)
			}
			switch action {
			case "start":
				_, err = b.Start(context.Background(), p, testOptions())
			case "restart":
				_, err = b.Restart(context.Background(), p, testOptions())
			case "stop":
				err = b.Stop(context.Background(), testOptions())
			case "down":
				err = b.Down(context.Background(), p, testOptions())
			}
			if err == nil || !strings.Contains(err.Error(), a.Root) {
				t.Fatalf("foreign %s was not rejected: %v", action, err)
			}
			after, err := a.Status()
			if err != nil || !after.Ready || after.Services[0].PID != initial.Services[0].PID {
				t.Fatalf("foreign command changed owner: %+v %v", after, err)
			}
		})
	}
}

func TestSharedProjectSelectionPersists(t *testing.T) {
	a, b := sharedPair(t)
	a.Project = "existing-dev-data"
	a.ProjectExplicit = true
	p := &fakeProvider{services: []string{"web"}}
	if _, err := a.Up(context.Background(), p, testOptions()); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(b.Root, "", Shared)
	if err != nil || reopened.Project != a.Project {
		t.Fatalf("explicit project not retained: %+v %v", reopened, err)
	}
	if _, err := b.Up(context.Background(), p, testOptions()); err != nil {
		t.Fatal(err)
	}
	if b.Project != a.Project {
		t.Fatal("concurrent stale opener changed project binding")
	}
}

func TestFailedHandoffRetainsOwnerAndSkipsMigration(t *testing.T) {
	a, b := sharedPair(t)
	p := &fakeProvider{services: []string{"web"}}
	if _, err := a.Up(context.Background(), p, testOptions()); err != nil {
		t.Fatal(err)
	}
	st, err := a.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	actual := st.Services[0]
	defer func() {
		st.Services = []ServiceRecord{actual}
		if err := a.WriteState(st); err != nil {
			t.Error(err)
		}
	}()
	st.Services[0].PID = -1
	st.Services[0].StartMarker = ""
	st.Services[0].Members = nil
	if err := a.WriteState(st); err != nil {
		t.Fatal(err)
	}
	next := &fakeProvider{services: []string{"web"}}
	if _, err := b.Up(context.Background(), next, testOptions()); err == nil {
		t.Fatal("handoff forgot an unverified live process group")
	}
	after, err := a.ReadState()
	if err != nil || after.Root != a.Root || len(after.Services) != 1 || len(next.migrated) != 0 {
		t.Fatalf("failed handoff lost owner or migrated: %+v %v", after, err)
	}
}

func TestConcurrentSharedStartupConvergesToOneOwner(t *testing.T) {
	a, b := sharedPair(t)
	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for _, stack := range []*Stack{a, b} {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := stack.Up(context.Background(), &fakeProvider{services: []string{"web"}}, testOptions())
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	st, err := a.ReadState()
	if err != nil || len(st.Services) != 1 || !isCurrent(st.Services[0]) || (st.Root != a.Root && st.Root != b.Root) {
		t.Fatalf("shared startups did not converge: %+v %v", st, err)
	}
}

func TestSharedBootstrapReusesSingleStoppedLegacyProject(t *testing.T) {
	legacy := newTestStack(t, t.TempDir())
	legacy.Project = "existing-data"
	if err := legacy.WriteState(&State{Phase: PhaseStopped}); err != nil {
		t.Fatal(err)
	}
	shared, err := Open(legacy.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	shared.Registry = legacy.Registry
	t.Cleanup(func() { _ = shared.Stop(context.Background(), testOptions()) })
	if _, err := shared.Up(context.Background(), &fakeProvider{services: []string{"web"}}, testOptions()); err != nil {
		t.Fatal(err)
	}
	if shared.Project != legacy.Project {
		t.Fatal("shared bootstrap created a fresh dataset")
	}
	if err := legacy.Down(context.Background(), &fakeProvider{}, testOptions()); err == nil {
		t.Fatal("legacy shutdown could stop adopted shared infrastructure")
	}
}

func TestSharedBootstrapRequiresChoiceBetweenLegacyDatasets(t *testing.T) {
	a, b := sharedPair(t)
	for _, root := range []string{a.Root, b.Root} {
		legacy, err := Open(root, "", Isolated)
		if err != nil {
			t.Fatal(err)
		}
		if err := legacy.WriteState(&State{Phase: PhaseStopped}); err != nil {
			t.Fatal(err)
		}
	}
	p := &fakeProvider{services: []string{"web"}}
	if _, err := a.Up(context.Background(), p, testOptions()); err == nil || !strings.Contains(err.Error(), "several existing dev datasets") {
		t.Fatalf("ambiguous data was selected: %v", err)
	}
	if p.composeUp != 0 || len(p.migrated) != 0 {
		t.Fatal("ambiguous bootstrap changed infrastructure")
	}
}

func TestStartCannotChangeStoppedProjectWithoutCompose(t *testing.T) {
	a, _ := sharedPair(t)
	if err := a.WriteState(&State{Phase: PhaseStopped}); err != nil {
		t.Fatal(err)
	}
	a.Project = "different-data"
	a.ProjectExplicit = true
	p := &fakeProvider{services: []string{"web"}}
	if _, err := a.Start(context.Background(), p, testOptions()); err == nil {
		t.Fatal("start changed project while retaining old infrastructure ports")
	}
}

func TestSharedWorktreesSelectSameInfrastructure(t *testing.T) {
	a := newTestStack(t, t.TempDir())
	bRoot := linkedWorktree(t, a.Root)
	first, err := Open(a.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Open(bRoot, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	if first.Project != second.Project || first.StateDir != second.StateDir {
		t.Fatalf("worktrees must share project and lifecycle state: %+v %+v", first, second)
	}
}

func TestProjectAliasesUseOneInfrastructureIdentity(t *testing.T) {
	base := newTestStack(t, t.TempDir())
	upper, err := Open(base.Root, "MY-DATA", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	lower, err := Open(base.Root, "my-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if upper.Project != lower.Project {
		t.Fatal("Docker-equivalent names bypass infrastructure identity")
	}
}
