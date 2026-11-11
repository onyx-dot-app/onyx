package metrics

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http/httptest"
	"strings"
	"syscall"
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
	m.ObserveRPC("UploadCapture", "OK", time.Minute)
	m.NodeReport(nil)
	m.KeyRegistration(nil)
	m.TemplateBuild(time.Second, TemplateBuilt)
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
		"craft_fc_host_agent_transfer_duration_seconds", "craft_fc_host_agent_node_reports_total",
		"craft_fc_host_agent_node_report_last_success_timestamp_seconds", "craft_fc_host_agent_key_registrations_total",
		"craft_fc_host_agent_key_registration_last_success_timestamp_seconds", "craft_fc_host_agent_template_builds_total",
		"craft_fc_host_agent_template_build_duration_seconds", "craft_fc_host_agent_template_ready",
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
# HELP craft_fc_host_agent_node_stats_errors 1 if the last scrape could not read node memory, disk, or the private memory of a VM.
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
	m.NodeReport(nil)
	m.KeyRegistration(nil)
	m.TemplateBuild(0, TemplateFailed)
}

func TestHandlerServesText(t *testing.T) {
	m, err := New(Source{VMs: func() []agent.VM { return nil }})
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(m.Server("", BearerAuth{Disabled: true}).Handler)
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

type statusErr int

func (e statusErr) Error() string   { return "http" }
func (e statusErr) HTTPStatus() int { return int(e) }

func TestPushResult(t *testing.T) {
	for err, want := range map[error]string{
		nil:                                    PushSuccess,
		statusErr(401):                         PushRejected,
		fmt.Errorf("wrap: %w", statusErr(409)): PushRejected,
		statusErr(503):                         PushServerError,
		statusErr(302):                         PushServerError,
		errors.New("dial tcp: refused"):        PushFailed,
	} {
		if got := PushResult(err); got != want {
			t.Errorf("PushResult(%v) = %s, want %s", err, got, want)
		}
	}
}

func TestNodeReportAndKeyRegistration(t *testing.T) {
	m, err := New(Source{})
	if err != nil {
		t.Fatal(err)
	}
	m.NodeReport(statusErr(503))
	m.KeyRegistration(statusErr(401))
	if testutil.ToFloat64(m.nodeReportLast) != 0 || testutil.ToFloat64(m.keyRegLast) != 0 {
		t.Fatal("a failure set the last success time")
	}
	before := float64(time.Now().Unix())
	m.NodeReport(nil)
	m.NodeReport(nil)
	m.NodeReport(errors.New("timeout"))
	m.KeyRegistration(nil)
	if r, k := testutil.ToFloat64(m.nodeReportLast), testutil.ToFloat64(m.keyRegLast); r < before || k < before {
		t.Fatalf("last success %v %v, want >= %v", r, k, before)
	}
	if err := testutil.GatherAndCompare(m.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_node_reports_total Node state reports to the api_server. result: success, rejected (HTTP 4xx), server_error (other HTTP), failed (no reply, or over the caps).
# TYPE craft_fc_host_agent_node_reports_total counter
craft_fc_host_agent_node_reports_total{result="failed"} 1
craft_fc_host_agent_node_reports_total{result="server_error"} 1
craft_fc_host_agent_node_reports_total{result="success"} 2
# HELP craft_fc_host_agent_key_registrations_total Node signing key registrations and refreshes. result: success, rejected (HTTP 4xx), server_error (other HTTP), failed (no reply).
# TYPE craft_fc_host_agent_key_registrations_total counter
craft_fc_host_agent_key_registrations_total{result="rejected"} 1
craft_fc_host_agent_key_registrations_total{result="success"} 1
`), "craft_fc_host_agent_node_reports_total", "craft_fc_host_agent_key_registrations_total"); err != nil {
		t.Error(err)
	}
}

func TestTemplateBuild(t *testing.T) {
	m, err := New(Source{})
	if err != nil {
		t.Fatal(err)
	}
	if testutil.ToFloat64(m.tplReady) != 0 {
		t.Fatal("ready before a build")
	}
	m.TemplateBuild(25*time.Second, TemplateBuilt)
	if testutil.ToFloat64(m.tplReady) != 1 {
		t.Fatal("not ready after a build")
	}
	m.TemplateBuild(time.Second, TemplateFailed)
	if testutil.ToFloat64(m.tplReady) != 0 {
		t.Fatal("ready after a failed build")
	}
	m.TemplateBuild(10*time.Millisecond, TemplateExisting)
	if testutil.ToFloat64(m.tplReady) != 1 {
		t.Fatal("not ready with an existing template")
	}
	for result, n := range map[string]float64{TemplateBuilt: 1, TemplateFailed: 1, TemplateExisting: 1} {
		if got := testutil.ToFloat64(m.tplBuilds.WithLabelValues(result)); got != n {
			t.Errorf("%s builds %v", result, got)
		}
	}
	if got := testutil.CollectAndCount(m.tplBuildSeconds); got != 3 {
		t.Fatalf("%d build histograms", got)
	}
}

func TestTransferHistogramOnlyForTransfers(t *testing.T) {
	m, err := New(Source{})
	if err != nil {
		t.Fatal(err)
	}
	m.ObserveRPC("Create", "OK", time.Second)
	m.ObserveRPC("UploadCapture", "OK", 400*time.Second)
	m.ObserveRPC("CaptureSession", "OK", 30*time.Second)
	m.ObserveRPC("RestoreSession", "DEADLINE_EXCEEDED", 600*time.Second)
	if got := testutil.CollectAndCount(m.transferSeconds); got != 3 {
		t.Fatalf("%d transfer histograms, want 3 (no Create)", got)
	}
	// rpc_duration_seconds keeps its buckets and every method.
	if got := testutil.CollectAndCount(m.rpcSeconds); got != 4 {
		t.Fatalf("%d rpc histograms", got)
	}
	fams, err := m.Registry().Gather()
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range fams {
		if f.GetName() != "craft_fc_host_agent_transfer_duration_seconds" {
			continue
		}
		for _, mt := range f.GetMetric() {
			bs := mt.GetHistogram().GetBucket()
			if top := bs[len(bs)-1].GetUpperBound(); top != 600 {
				t.Fatalf("top bucket %v", top)
			}
			if mt.GetLabel()[0].GetValue() == "UploadCapture" && bs[len(bs)-2].GetCumulativeCount() != 1 {
				t.Fatalf("a 400 s upload is not under 450 s: %v", bs)
			}
		}
	}
}

func TestPrivateMemory(t *testing.T) {
	vms := []agent.VM{
		{State: pb.VMState_VM_STATE_RUNNING, PID: 10, MemMiB: 4096},
		{State: pb.VMState_VM_STATE_RUNNING, PID: 11, MemMiB: 4096},
		{State: pb.VMState_VM_STATE_STARTING, PID: 12, MemMiB: 4096},
		{State: pb.VMState_VM_STATE_EXITED, PID: 13, MemMiB: 4096},
		{State: pb.VMState_VM_STATE_STARTING, MemMiB: 4096},
	}
	read := map[int]error{}
	m, err := New(Source{VMs: func() []agent.VM { return vms }, PrivateMem: func(pid int) (uint64, error) {
		if err := read[pid]; err != nil {
			return 0, err
		}
		if pid == 13 {
			t.Error("read an exited VM")
		}
		return uint64(pid) << 20, nil
	}})
	if err != nil {
		t.Fatal(err)
	}
	want := func(bytes, failed string) string {
		return `
# HELP craft_fc_host_agent_vm_memory_private_bytes Anonymous memory (smaps_rollup) of the Firecracker processes of the VMs that are not exited: the guest pages each VM wrote, plus the VMM's own heap. Page cache of the snapshot memory files is not in it. Balloon free page reporting and the guest's idle reclaim lower it.
# TYPE craft_fc_host_agent_vm_memory_private_bytes gauge
craft_fc_host_agent_vm_memory_private_bytes ` + bytes + `
# HELP craft_fc_host_agent_node_stats_errors 1 if the last scrape could not read node memory, disk, or the private memory of a VM.
# TYPE craft_fc_host_agent_node_stats_errors gauge
craft_fc_host_agent_node_stats_errors{stat="vm_memory"} ` + failed + `
`
	}
	names := []string{"craft_fc_host_agent_vm_memory_private_bytes", "craft_fc_host_agent_node_stats_errors"}
	// 10 + 11 + 12 MiB.
	if err := testutil.GatherAndCompare(m.Registry(), strings.NewReader(want("3.4603008e+07", "0")), names...); err != nil {
		t.Error(err)
	}
	// A VM that exits during the scrape is skipped (open or read).
	read[10] = fs.ErrNotExist
	read[12] = fmt.Errorf("read: %w", syscall.ESRCH)
	if err := testutil.GatherAndCompare(m.Registry(), strings.NewReader(want("1.1534336e+07", "0")), names...); err != nil {
		t.Error(err)
	}
	// Another error is flagged and the partial sum is not reported.
	read[11] = errors.New("permission denied")
	if err := testutil.GatherAndCompare(m.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_node_stats_errors 1 if the last scrape could not read node memory, disk, or the private memory of a VM.
# TYPE craft_fc_host_agent_node_stats_errors gauge
craft_fc_host_agent_node_stats_errors{stat="vm_memory"} 1
`), names...); err != nil {
		t.Error(err)
	}
}
