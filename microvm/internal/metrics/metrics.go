// Package metrics holds the Prometheus metrics of the host agent.
//
// Gauges that describe the VM table and the node (VM count by state, node
// memory, allocated memory, open relay connections and Dial streams) are read
// at scrape time from one pass over the agent's state (observable gauges with
// a collect callback). So the agent keeps no per-VM metric state and needs no
// goroutine per VM. No metric has a sandbox or tenant label: per-VM detail is
// in the audit and guest log lines.
package metrics

import (
	"net/http"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const namespace = "craft_fc_host_agent"

// Admission results of Create.
const (
	Admitted = "admitted"
	Refused  = "refused"
	Failed   = "failed"
)

// Source reads the agent state at scrape time. A nil func reports nothing.
type Source struct {
	VMs   func() []agent.VM
	Stats agent.HostStats
	// RelayConns returns the open egress relay connections of the node.
	RelayConns func() int
	// DialStreams returns the open Dial streams of the node.
	DialStreams func() int
}

// Metrics are the agent's metrics on their own registry.
type Metrics struct {
	reg *prometheus.Registry

	createSeconds *prometheus.HistogramVec
	admissions    *prometheus.CounterVec
	rpcs          *prometheus.CounterVec
	rpcSeconds    *prometheus.HistogramVec
	passthrough   *prometheus.CounterVec
	relayConns    *prometheus.CounterVec
	guestLog      *prometheus.CounterVec
	guestDropped  *prometheus.CounterVec
}

// New registers the agent metrics, the state collector for src, and the Go
// and process collectors on a new registry.
func New(src Source) (*Metrics, error) {
	m := &Metrics{
		reg: prometheus.NewRegistry(),
		createSeconds: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: namespace, Name: "create_duration_seconds",
			Help:    "Create latency. result: created (a VM started), existing (idempotent repeat), refused, failed.",
			Buckets: []float64{0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60},
		}, []string{"result"}),
		admissions: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "admissions_total",
			Help: "Create admission decisions. result: admitted, refused (reason = ErrorReason), failed (the start failed after admission).",
		}, []string{"result", "reason"}),
		rpcs: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "rpc_requests_total",
			Help: "HostAgent API calls by method and gRPC status code.",
		}, []string{"method", "code"}),
		rpcSeconds: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: namespace, Name: "rpc_duration_seconds",
			Help:    "HostAgent API call duration by method. Dial counts the whole stream.",
			Buckets: prometheus.DefBuckets,
		}, []string{"method"}),
		passthrough: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "passthrough_calls_total",
			Help: "Guest daemon pass-through calls by daemon method and gRPC status code.",
		}, []string{"method", "code"}),
		relayConns: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "relay_connections_total",
			Help: "Egress relay connections from VMs. result: accepted, over_cap (closed at once), upstream_failed.",
		}, []string{"result"}),
		guestLog: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "guest_log_bytes_total",
			Help: "Guest log bytes written to stdout. stream: console (serial console), firecracker.",
		}, []string{"stream"}),
		guestDropped: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "guest_log_dropped_bytes_total",
			Help: "Guest log bytes dropped by the per-VM or node rate limit.",
		}, []string{"stream"}),
	}
	cs := []prometheus.Collector{
		m.createSeconds, m.admissions, m.rpcs, m.rpcSeconds, m.passthrough, m.relayConns, m.guestLog, m.guestDropped,
		newStateCollector(src),
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
	}
	for _, c := range cs {
		if err := m.reg.Register(c); err != nil {
			return nil, err
		}
	}
	return m, nil
}

// Registry returns the registry, for tests.
func (m *Metrics) Registry() *prometheus.Registry { return m.reg }

// Handler serves the metrics in the Prometheus text format.
func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.reg, promhttp.HandlerOpts{Registry: m.reg})
}

// Server returns an HTTP server for /metrics on addr, behind auth.
func (m *Metrics) Server(addr string, auth BearerAuth) *http.Server {
	mux := http.NewServeMux()
	mux.Handle("/metrics", auth.Wrap(m.Handler()))
	return &http.Server{
		Addr: addr, Handler: mux,
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second,
	}
}

// Create results.
const (
	CreateCreated  = "created"
	CreateExisting = "existing"
	CreateRefused  = "refused"
	CreateFailed   = "failed"
)

// ObserveCreate records one Create: its latency by result, and the admission
// decision. reason is the ErrorReason name for refused and failed.
func (m *Metrics) ObserveCreate(d time.Duration, result, reason string) {
	if m == nil {
		return
	}
	m.createSeconds.WithLabelValues(result).Observe(d.Seconds())
	switch result {
	case CreateCreated:
		m.admissions.WithLabelValues(Admitted, "").Inc()
	case CreateRefused:
		m.admissions.WithLabelValues(Refused, reason).Inc()
	case CreateFailed:
		m.admissions.WithLabelValues(Failed, reason).Inc()
	}
}

// ObserveRPC records one HostAgent call.
func (m *Metrics) ObserveRPC(method, code string, d time.Duration) {
	if m == nil {
		return
	}
	m.rpcs.WithLabelValues(method, code).Inc()
	m.rpcSeconds.WithLabelValues(method).Observe(d.Seconds())
}

// ObservePassthrough records one guest daemon call.
func (m *Metrics) ObservePassthrough(method, code string) {
	if m == nil {
		return
	}
	m.passthrough.WithLabelValues(method, code).Inc()
}

// RelayEvent counts one relay connection event.
func (m *Metrics) RelayEvent(result string) {
	if m == nil {
		return
	}
	m.relayConns.WithLabelValues(result).Inc()
}

// GuestLog counts shipped and dropped guest log bytes.
func (m *Metrics) GuestLog(stream string, shipped, dropped int) {
	if m == nil {
		return
	}
	if shipped > 0 {
		m.guestLog.WithLabelValues(stream).Add(float64(shipped))
	}
	if dropped > 0 {
		m.guestDropped.WithLabelValues(stream).Add(float64(dropped))
	}
}

// stateCollector reads the VM table and the node at scrape time.
type stateCollector struct {
	src         Source
	vms         *prometheus.Desc
	memTotal    *prometheus.Desc
	memAvail    *prometheus.Desc
	diskFree    *prometheus.Desc
	memAlloc    *prometheus.Desc
	vcpuAlloc   *prometheus.Desc
	relayOpen   *prometheus.Desc
	dialOpen    *prometheus.Desc
	statsFailed *prometheus.Desc
}

func newStateCollector(src Source) *stateCollector {
	d := func(name, help string, labels ...string) *prometheus.Desc {
		return prometheus.NewDesc(prometheus.BuildFQName(namespace, "", name), help, labels, nil)
	}
	return &stateCollector{
		src:         src,
		vms:         d("vms", "VMs in the agent's table by state (starting, running, exited).", "state"),
		memTotal:    d("node_memory_total_bytes", "Node MemTotal."),
		memAvail:    d("node_memory_available_bytes", "Node MemAvailable (the admission input)."),
		diskFree:    d("node_disk_free_bytes", "Free space on the data disk."),
		memAlloc:    d("vm_memory_allocated_bytes", "Guest memory of the VMs that are not exited."),
		vcpuAlloc:   d("vm_vcpus_allocated", "vCPUs of the VMs that are not exited."),
		relayOpen:   d("relay_open_connections", "Open egress relay connections."),
		dialOpen:    d("dial_open_streams", "Open Dial streams."),
		statsFailed: d("node_stats_errors", "1 if the last scrape could not read node memory or disk.", "stat"),
	}
}

func (c *stateCollector) Describe(ch chan<- *prometheus.Desc) {
	for _, d := range []*prometheus.Desc{
		c.vms, c.memTotal, c.memAvail, c.diskFree, c.memAlloc, c.vcpuAlloc, c.relayOpen, c.dialOpen, c.statsFailed,
	} {
		ch <- d
	}
}

// stateLabel is the VMState name without the prefix, in lower case.
func stateLabel(s pb.VMState) string {
	return strings.ToLower(strings.TrimPrefix(s.String(), "VM_STATE_"))
}

func (c *stateCollector) Collect(ch chan<- prometheus.Metric) {
	gauge := func(d *prometheus.Desc, v float64, labels ...string) {
		ch <- prometheus.MustNewConstMetric(d, prometheus.GaugeValue, v, labels...)
	}
	if c.src.VMs != nil {
		counts := map[pb.VMState]int{}
		var mem, vcpus uint64
		for _, vm := range c.src.VMs() {
			counts[vm.State]++
			if vm.State != pb.VMState_VM_STATE_EXITED {
				mem += uint64(vm.MemMiB) << 20
				vcpus += uint64(vm.VCPUs)
			}
		}
		// Every state is reported, also at 0, so the series do not vanish.
		for _, s := range []pb.VMState{pb.VMState_VM_STATE_STARTING, pb.VMState_VM_STATE_RUNNING, pb.VMState_VM_STATE_EXITED} {
			gauge(c.vms, float64(counts[s]), stateLabel(s))
		}
		gauge(c.memAlloc, float64(mem))
		gauge(c.vcpuAlloc, float64(vcpus))
	}
	if c.src.Stats != nil {
		total, avail, err := c.src.Stats.MemInfo()
		if err == nil {
			gauge(c.memTotal, float64(total<<20))
			gauge(c.memAvail, float64(avail<<20))
		}
		gauge(c.statsFailed, boolFloat(err != nil), "memory")
		free, err := c.src.Stats.DiskFreeBytes()
		if err == nil {
			gauge(c.diskFree, float64(free))
		}
		gauge(c.statsFailed, boolFloat(err != nil), "disk")
	}
	if c.src.RelayConns != nil {
		gauge(c.relayOpen, float64(c.src.RelayConns()))
	}
	if c.src.DialStreams != nil {
		gauge(c.dialOpen, float64(c.src.DialStreams()))
	}
}

func boolFloat(b bool) float64 {
	if b {
		return 1
	}
	return 0
}
