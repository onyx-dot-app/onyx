//go:build !windows

package devstack

import (
	"context"
	"os/exec"
	"syscall"
	"testing"
)

// livePGroup starts a process in its own group that holds no port.
func livePGroup(t *testing.T) int {
	t.Helper()
	cmd := exec.Command("sleep", "300")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	return cmd.Process.Pid
}

func fakeContainersRunning(t *testing.T, running bool) {
	t.Helper()
	original := projectContainersRunning
	projectContainersRunning = func(string) (bool, error) { return running, nil }
	t.Cleanup(func() { projectContainersRunning = original })
}

// foreignOwner writes a lease for another stack whose state has phase and
// services.
func foreignOwner(t *testing.T, registry *Registry, name string, port int, phase string, services []ServiceRecord) (root, stateDir string) {
	t.Helper()
	root = t.TempDir()
	owner := &Stack{Root: root, StateDir: t.TempDir(), Project: "foreign-data", Mode: Isolated}
	if err := owner.WriteState(&State{Phase: phase, Services: services, Ports: map[string]int{name: port}}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.LeaseFor(root, owner.StateDir, []PortRequest{{Name: name, Fixed: port}}); err != nil {
		t.Fatal(err)
	}
	return root, owner.StateDir
}

func leaseNames(t *testing.T, registry *Registry, root string) map[string]int {
	t.Helper()
	leases, err := registry.Leases()
	if err != nil {
		t.Fatal(err)
	}
	names := map[string]int{}
	for _, l := range leases {
		if l.Root == root {
			names[l.Name] = l.Port
		}
	}
	return names
}

func TestLeaseReclaimsStoppedOwnerWithDeadProcesses(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	port := freeBasePort() + 300
	dead := ServiceRecord{Slug: "web", PID: 1 << 22, PGID: 1 << 22}
	owner, stateDir := foreignOwner(t, registry, "web", port, PhaseStopped, []ServiceRecord{dead})
	got, err := registry.LeaseFor(t.TempDir(), "", []PortRequest{{Name: "web", Preferred: port}})
	if err != nil {
		t.Fatal(err)
	}
	if got["web"] != port {
		t.Fatalf("abandoned lease was not reclaimed: got %d, want %d", got["web"], port)
	}
	if len(leaseNames(t, registry, owner)) != 0 {
		t.Fatal("reclaimed lease is still recorded for its old owner")
	}
	if leases, _ := registry.Leases(); leases[0].StateDir == "" && leases[0].Root == owner {
		t.Fatalf("lease lost its state directory: %s", stateDir)
	}
}

func TestLeaseSkipsOwnerWithLiveProcessGroup(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	port := freeBasePort() + 310
	pid := livePGroup(t)
	foreignOwner(t, registry, "web", port, PhaseStopped, []ServiceRecord{{Slug: "worker", PID: pid, PGID: pid}})
	got, err := registry.LeaseFor(t.TempDir(), "", []PortRequest{{Name: "web", Preferred: port}})
	if err != nil {
		t.Fatal(err)
	}
	if got["web"] == port {
		t.Fatal("took the lease of a stack with a live process group")
	}
}

func TestLeaseSkipsOwnerThatIsNotStopped(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	port := freeBasePort() + 320
	foreignOwner(t, registry, "web", port, PhaseDegraded, nil)
	got, err := registry.LeaseFor(t.TempDir(), "", []PortRequest{{Name: "web", Preferred: port}})
	if err != nil {
		t.Fatal(err)
	}
	if got["web"] == port {
		t.Fatal("took the lease of an unhealthy but live stack")
	}
}

func TestLeaseReclaimsInfrastructurePortOnlyWithoutRunningContainers(t *testing.T) {
	for _, running := range []bool{true, false} {
		registry := &Registry{Dir: t.TempDir()}
		port := freeBasePort() + 330
		fakeContainersRunning(t, running)
		foreignOwner(t, registry, "POSTGRES_HOST_PORT", port, PhaseStopped, nil)
		got, err := registry.LeaseFor(t.TempDir(), "", []PortRequest{{Name: "POSTGRES_HOST_PORT", Preferred: port}})
		if err != nil {
			t.Fatal(err)
		}
		if reclaimed := got["POSTGRES_HOST_PORT"] == port; reclaimed == running {
			t.Fatalf("containers running=%v, reclaimed=%v", running, reclaimed)
		}
	}
}

func TestLeaseMovesStoppedServiceDownToLowestFreePort(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	root := t.TempDir()
	base := freeBasePort() + 340
	if _, err := registry.LeaseFor(root, "", []PortRequest{{Name: "web", Fixed: base + 5}}); err != nil {
		t.Fatal(err)
	}
	running, err := registry.LeaseFor(root, "", []PortRequest{{Name: "web", Preferred: base, Running: true}})
	if err != nil || running["web"] != base+5 {
		t.Fatalf("running service moved: %v %v", running, err)
	}
	stopped, err := registry.LeaseFor(root, "", []PortRequest{{Name: "web", Preferred: base}})
	if err != nil || stopped["web"] != base {
		t.Fatalf("stopped service did not move down: %v %v", stopped, err)
	}
}

func TestReleaseNamesKeepsOtherLeases(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	root, other := t.TempDir(), t.TempDir()
	base := freeBasePort() + 360
	if _, err := registry.LeaseFor(root, "", []PortRequest{{Name: "web", Fixed: base}, {Name: "POSTGRES_HOST_PORT", Fixed: base + 1}}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.LeaseFor(other, "", []PortRequest{{Name: "web", Fixed: base + 2}}); err != nil {
		t.Fatal(err)
	}
	if err := registry.ReleaseNames(root, []string{"web"}); err != nil {
		t.Fatal(err)
	}
	if got := leaseNames(t, registry, root); len(got) != 1 || got["POSTGRES_HOST_PORT"] != base+1 {
		t.Fatalf("leases of root = %v", got)
	}
	if got := leaseNames(t, registry, other); got["web"] != base+2 {
		t.Fatalf("another root lost its lease: %v", got)
	}
}

func TestStopReleasesAppLeasesAndDownReleasesAll(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web", "api"}, infra: []PortRequest{{Name: "POSTGRES_HOST_PORT", Preferred: testBasePort + 500}}}
	mustUp(t, s, p)
	if got := leaseNames(t, s.Registry, s.Root); len(got) != 3 {
		t.Fatalf("leases after up = %v", got)
	}
	if err := s.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}
	if got := leaseNames(t, s.Registry, s.Root); len(got) != 1 || got["POSTGRES_HOST_PORT"] == 0 {
		t.Fatalf("stop must keep only infrastructure leases: %v", got)
	}
	mustUp(t, s, p)
	if err := s.Down(context.Background(), p, testOptions()); err != nil {
		t.Fatal(err)
	}
	if got := leaseNames(t, s.Registry, s.Root); len(got) != 0 {
		t.Fatalf("down must release every lease: %v", got)
	}
}
