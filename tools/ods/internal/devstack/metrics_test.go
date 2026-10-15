//go:build !windows

package devstack

import (
	"context"
	"fmt"
	"net"
	"strings"
	"testing"
)

func TestMetricsLeaseMovesOffForeignListener(t *testing.T) {
	stack := newTestStack(t, t.TempDir())
	provider := &fakeProvider{services: []string{"celery-primary"}}
	mustUp(t, stack, provider)
	state, err := stack.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	requests := []PortRequest{{Name: "celery-primary-metrics", Preferred: testBasePort + 100}}
	if err := stack.leasePorts(state, append([]PortRequest(nil), requests...)); err != nil {
		t.Fatal(err)
	}
	port := state.Ports[requests[0].Name]

	// Nothing else holds the port: the running worker keeps it.
	if err := stack.leasePorts(state, append([]PortRequest(nil), requests...)); err != nil {
		t.Fatal(err)
	}
	if got := state.Ports[requests[0].Name]; got != port {
		t.Fatalf("free metrics port moved from %d to %d", port, got)
	}

	// A foreign process took the port while the worker runs: the lease
	// moves so the next start restores a metrics endpoint.
	listener, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = listener.Close() }()
	if err := stack.leasePorts(state, append([]PortRequest(nil), requests...)); err != nil {
		t.Fatal(err)
	}
	moved := state.Ports[requests[0].Name]
	if moved == port {
		t.Fatal("running worker kept a metrics port held by a foreign listener")
	}
	if err := stack.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}
	state, err = stack.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	if err := stack.leasePorts(state, append([]PortRequest(nil), requests...)); err != nil {
		t.Fatal(err)
	}
	if got := state.Ports[requests[0].Name]; got != moved {
		t.Fatalf("stopped worker lost its free metrics port: %d -> %d", moved, got)
	}
}

func TestMetricsPortsFollowProfile(t *testing.T) {
	for _, tc := range []struct {
		profile string
		count   int
	}{{ProfileMinimal, 0}, {ProfileDefault, 4}, {ProfileFull, 6}} {
		t.Run(tc.profile, func(t *testing.T) {
			count := 0
			for _, req := range AppPortRequests(Options{Profile: tc.profile}) {
				if strings.HasSuffix(req.Name, "-metrics") {
					count++
				}
			}
			if count != tc.count {
				t.Fatalf("metrics requests = %d, want %d", count, tc.count)
			}
		})
	}
}

func TestMetricsAssignmentsAreServiceLocalAndStable(t *testing.T) {
	root, launch := writeLaunchFixture(t)
	opts := Options{Profile: ProfileFull}
	ports := map[string]int{}
	for i, req := range AppPortRequests(opts) {
		ports[req.Name] = 24000 + i
	}
	env := Env{Base: []string{"PROMETHEUS_METRICS_PORT=9999"}}
	first, err := LaunchPlan(root, launch, ports, env, opts)
	if err != nil {
		t.Fatal(err)
	}
	second, err := LaunchPlan(root, launch, ports, env, opts)
	if err != nil {
		t.Fatal(err)
	}
	workers := 0
	for i, sp := range first {
		want := "9999"
		if port := ports[sp.Slug+"-metrics"]; port > 0 {
			workers++
			want = fmt.Sprint(port)
			if sp.Port != 0 || sp.Health != "" {
				t.Fatalf("metrics port became worker readiness/bind port: %+v", sp)
			}
		}
		if got := EnvValue(sp.Env, "PROMETHEUS_METRICS_PORT"); got != want {
			t.Errorf("%s metrics port = %s, want %s", sp.Slug, got, want)
		}
		if sp.Hash() != second[i].Hash() {
			t.Errorf("repeated plan changed hash for %s", sp.Slug)
		}
	}
	if workers != 2 {
		t.Fatalf("fixture must exercise two independently assigned workers, got %d", workers)
	}
}
