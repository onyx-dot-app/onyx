package metrics

import (
	"errors"
	"io"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus/testutil"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

type fakeStats struct{ diskErr error }

func (fakeStats) MemInfo() (uint64, uint64, error) { return 8192, 2048, nil }
func (s fakeStats) DiskFreeBytes() (uint64, error) { return 5 << 30, s.diskErr }

func TestRegistrationAndNames(t *testing.T) {
	m, err := New(Source{})
	if err != nil {
		t.Fatal(err)
	}
	// A second set registers on its own registry.
	if _, err := New(Source{}); err != nil {
		t.Fatal(err)
	}
	m.ObserveCreate(time.Second, CreateCreated, "")
	m.ObserveRPC("Create", "OK", time.Second)
	m.ObservePassthrough("Init", "OK")
	m.RelayEvent("accepted")
	m.GuestLog("console", 10, 5)
	fams, err := m.Registry().Gather()
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]bool{}
	for _, f := range fams {
		got[f.GetName()] = true
	}
	for _, n := range []string{
		"craft_fc_host_agent_create_duration_seconds", "craft_fc_host_agent_admissions_total",
		"craft_fc_host_agent_rpc_requests_total", "craft_fc_host_agent_rpc_duration_seconds",
		"craft_fc_host_agent_passthrough_calls_total", "craft_fc_host_agent_relay_connections_total",
		"craft_fc_host_agent_guest_log_bytes_total", "craft_fc_host_agent_guest_log_dropped_bytes_total",
		"go_goroutines",
	} {
		if !got[n] {
			t.Errorf("%s is not registered", n)
		}
	}
	// Every name is lint-clean for Prometheus.
	probs, err := testutil.GatherAndLint(m.Registry())
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range probs {
		if strings.HasPrefix(p.Metric, namespace) {
			t.Errorf("lint %s: %s", p.Metric, p.Text)
		}
	}
}

func TestStateCollectorReadsAtScrape(t *testing.T) {
	vms := []agent.VM{
		{State: pb.VMState_VM_STATE_RUNNING, MemMiB: 1024, VCPUs: 2},
		{State: pb.VMState_VM_STATE_RUNNING, MemMiB: 2048, VCPUs: 4},
		{State: pb.VMState_VM_STATE_STARTING, MemMiB: 1024, VCPUs: 2},
		{State: pb.VMState_VM_STATE_EXITED, MemMiB: 4096, VCPUs: 8},
	}
	m, err := New(Source{
		VMs: func() []agent.VM { return vms }, Stats: fakeStats{diskErr: errors.New("statfs")},
		RelayConns: func() int { return 7 }, DialStreams: func() int { return 3 },
	})
	if err != nil {
		t.Fatal(err)
	}
	want := `
# HELP craft_fc_host_agent_vms VMs in the agent's table by state (starting, running, exited).
# TYPE craft_fc_host_agent_vms gauge
craft_fc_host_agent_vms{state="exited"} 1
craft_fc_host_agent_vms{state="running"} 2
craft_fc_host_agent_vms{state="starting"} 1
# HELP craft_fc_host_agent_vm_memory_allocated_bytes Guest memory of the VMs that are not exited.
# TYPE craft_fc_host_agent_vm_memory_allocated_bytes gauge
craft_fc_host_agent_vm_memory_allocated_bytes 4.294967296e+09
# HELP craft_fc_host_agent_vm_vcpus_allocated vCPUs of the VMs that are not exited.
# TYPE craft_fc_host_agent_vm_vcpus_allocated gauge
craft_fc_host_agent_vm_vcpus_allocated 8
# HELP craft_fc_host_agent_node_memory_available_bytes Node MemAvailable (the admission input).
# TYPE craft_fc_host_agent_node_memory_available_bytes gauge
craft_fc_host_agent_node_memory_available_bytes 2.147483648e+09
# HELP craft_fc_host_agent_node_stats_errors 1 if the last scrape could not read node memory or disk.
# TYPE craft_fc_host_agent_node_stats_errors gauge
craft_fc_host_agent_node_stats_errors{stat="disk"} 1
craft_fc_host_agent_node_stats_errors{stat="memory"} 0
# HELP craft_fc_host_agent_relay_open_connections Open egress relay connections.
# TYPE craft_fc_host_agent_relay_open_connections gauge
craft_fc_host_agent_relay_open_connections 7
# HELP craft_fc_host_agent_dial_open_streams Open Dial streams.
# TYPE craft_fc_host_agent_dial_open_streams gauge
craft_fc_host_agent_dial_open_streams 3
`
	names := []string{
		"craft_fc_host_agent_vms", "craft_fc_host_agent_vm_memory_allocated_bytes", "craft_fc_host_agent_vm_vcpus_allocated",
		"craft_fc_host_agent_node_memory_available_bytes", "craft_fc_host_agent_node_stats_errors",
		"craft_fc_host_agent_relay_open_connections", "craft_fc_host_agent_dial_open_streams",
		// No disk free gauge: the read failed.
		"craft_fc_host_agent_node_disk_free_bytes",
	}
	if err := testutil.GatherAndCompare(m.Registry(), strings.NewReader(want), names...); err != nil {
		t.Error(err)
	}
	// The table is read again at the next scrape.
	vms = vms[:1]
	if err := testutil.GatherAndCompare(m.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_vms VMs in the agent's table by state (starting, running, exited).
# TYPE craft_fc_host_agent_vms gauge
craft_fc_host_agent_vms{state="exited"} 0
craft_fc_host_agent_vms{state="running"} 1
craft_fc_host_agent_vms{state="starting"} 0
`), "craft_fc_host_agent_vms"); err != nil {
		t.Error(err)
	}
}

func TestAdmissionResults(t *testing.T) {
	m, err := New(Source{})
	if err != nil {
		t.Fatal(err)
	}
	m.ObserveCreate(time.Second, CreateCreated, "")
	m.ObserveCreate(time.Millisecond, CreateExisting, "")
	m.ObserveCreate(time.Millisecond, CreateRefused, "CAPACITY_MEMORY")
	m.ObserveCreate(time.Millisecond, CreateRefused, "CAPACITY_MEMORY")
	m.ObserveCreate(time.Second, CreateFailed, "VMM_FAILED")
	if err := testutil.GatherAndCompare(m.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_admissions_total Create admission decisions. result: admitted, refused (reason = ErrorReason), failed (the start failed after admission).
# TYPE craft_fc_host_agent_admissions_total counter
craft_fc_host_agent_admissions_total{reason="",result="admitted"} 1
craft_fc_host_agent_admissions_total{reason="CAPACITY_MEMORY",result="refused"} 2
craft_fc_host_agent_admissions_total{reason="VMM_FAILED",result="failed"} 1
`), "craft_fc_host_agent_admissions_total"); err != nil {
		t.Error(err)
	}
}

func TestNilMetricsIsSafe(t *testing.T) {
	var m *Metrics
	m.ObserveCreate(time.Second, CreateCreated, "")
	m.ObserveRPC("x", "OK", 0)
	m.ObservePassthrough("x", "OK")
	m.RelayEvent("accepted")
	m.GuestLog("console", 1, 1)
}

func TestHandlerServesText(t *testing.T) {
	m, err := New(Source{VMs: func() []agent.VM { return nil }})
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(m.Server("").Handler)
	defer srv.Close()
	resp, err := srv.Client().Get(srv.URL + "/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || !strings.Contains(string(body), `craft_fc_host_agent_vms{state="running"} 0`) {
		t.Fatalf("status %d body:\n%s", resp.StatusCode, body)
	}
}
