//go:build !windows

package devstack

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestWebPreviewUsesManagedAPIWithoutChangingItsState(t *testing.T) {
	for _, mode := range []Mode{Shared, Isolated} {
		t.Run(string(mode), func(t *testing.T) {
			base := newTestStack(t, t.TempDir())
			source, err := Open(base.Root, "", mode)
			if err != nil {
				t.Fatal(err)
			}
			source.Registry = base.Registry
			t.Cleanup(func() { _ = source.Stop(context.Background(), testOptions()) })
			mustUp(t, source, &fakeProvider{services: []string{"api"}})
			api := servicePID(t, source, "api")
			before, err := os.ReadFile(filepath.Join(source.StateDir, stateFileName))
			if err != nil {
				t.Fatal(err)
			}
			target, err := ResolveTarget(source.Root, "", mode)
			if err != nil {
				t.Fatal(err)
			}
			preview, err := Open(source.Root, target.Project, Frontend)
			if err != nil {
				t.Fatal(err)
			}
			release, err := preview.lockFrontendService(context.Background(), target, testOptions().LockWait)
			if err != nil {
				t.Fatal(err)
			}
			release()
			after, err := os.ReadFile(filepath.Join(source.StateDir, stateFileName))
			if err != nil || !reflect.DeepEqual(before, after) || !isCurrent(api) {
				t.Fatalf("API state changed: %v", err)
			}
			if target.Ports["api"] != api.Port {
				t.Fatal("preview lost API endpoint")
			}
		})
	}
}

func TestWebPreviewRequiresHealthyManagedAPI(t *testing.T) {
	source := newTestStack(t, t.TempDir())
	target, err := ResolveTarget(source.Root, "", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	preview, err := Open(source.Root, target.Project, Frontend)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := preview.lockFrontendService(context.Background(), target, testOptions().LockWait); err == nil || !strings.Contains(err.Error(), "API") {
		t.Fatalf("missing API accepted: %v", err)
	}
}

func TestWebPreviewRejectsLocalDuplicateEvenWithSharedAPI(t *testing.T) {
	a, b := sharedPair(t)
	mustUp(t, a, &fakeProvider{services: []string{"api"}})
	local, err := Open(b.Root, "", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	local.Registry = a.Registry
	t.Cleanup(func() { _ = local.Stop(context.Background(), testOptions()) })
	mustUp(t, local, &fakeProvider{services: []string{"api", "web"}})
	web := servicePID(t, local, "web")
	target, err := ResolveTarget(b.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	preview, err := Open(b.Root, target.Project, Frontend)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := preview.lockFrontendService(context.Background(), target, testOptions().LockWait); err == nil || !strings.Contains(err.Error(), "frontend already runs") {
		t.Fatalf("duplicate accepted: %v", err)
	}
	if !isCurrent(web) {
		t.Fatal("existing web process stopped")
	}
}

func TestFullStackHandoffStopsPreviewBeforeMigration(t *testing.T) {
	source := newTestStack(t, t.TempDir())
	mustUp(t, source, &fakeProvider{services: []string{"api"}})
	preview, err := Open(source.Root, source.Project, Frontend)
	if err != nil {
		t.Fatal(err)
	}
	preview.Registry = source.Registry
	port := freeBasePort()
	specs, err := (&fakeProvider{services: []string{"web"}}).Plan(preview.Root, map[string]int{"web": port}, Env{}, testOptions())
	if err != nil {
		t.Fatal(err)
	}
	record, err := startService(specs[0], filepath.Join(preview.LogDir(), "web.log"))
	if err != nil {
		t.Fatal(err)
	}
	if err := preview.WriteState(&State{Services: []ServiceRecord{record}, Ports: map[string]int{"web": port}, Phase: PhaseReady}); err != nil {
		t.Fatal(err)
	}
	if _, err := preview.Registry.LeaseFor(preview.StateDir, preview.StateDir, []PortRequest{{Name: "web", Fixed: port}}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = preview.stopServices(testOptions().StopTimeout) })
	next, err := source.Up(context.Background(), &handoffProvider{fakeProvider: &fakeProvider{services: []string{"api", "web"}}, previous: record}, testOptions())
	if err != nil {
		t.Fatal(err)
	}
	if !next.Ready || next.Ports["web"] != port || isCurrent(record) {
		t.Fatalf("handoff did not retain preview port safely: %+v", next)
	}
	state, err := preview.ReadState()
	if err != nil || len(state.Services) > 0 {
		t.Fatalf("preview still owns full-stack web: %+v %v", state, err)
	}
	if got := leaseNames(t, source.Registry, preview.StateDir); len(got) != 0 {
		t.Fatalf("handoff kept the preview's leases: %v", got)
	}
}
