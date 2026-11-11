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
	"errors"
	"io/fs"
	"net/http"
	"strings"
	"syscall"
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
	// PrivateMem returns the private memory bytes of a Firecracker process
	// (hostinfo.PrivateMemoryBytes). Nil: not reported.
	PrivateMem func(pid int) (uint64, error)
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

	transferSeconds *prometheus.HistogramVec
	nodeReports     *prometheus.CounterVec
	nodeReportLast  prometheus.Gauge
	keyRegs         *prometheus.CounterVec
	keyRegLast      prometheus.Gauge
	tplBuilds       *prometheus.CounterVec
	tplBuildSeconds *prometheus.HistogramVec
	tplReady        prometheus.Gauge
	imageGCRemoved  *prometheus.CounterVec
}

// transferMethods move a session over the network or disk; they get the
// transfer histogram as well as rpc_duration_seconds.
var transferMethods = map[string]bool{"CaptureSession": true, "UploadCapture": true, "RestoreSession": true}

// Results of the node state report and the key registration.
const (
	PushSuccess = "success"
	// PushRejected is an HTTP 4xx from the api_server.
	PushRejected = "rejected"
	// PushServerError is any other reply that is not 2xx.
	PushServerError = "server_error"
	// PushFailed is no reply: a network error, a timeout, or a report over
	// the caps.
	PushFailed = "failed"
)

// Results of a template build.
const (
	TemplateBuilt    = "built"
	TemplateExisting = "existing"
	TemplateFailed   = "failed"
)

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
		transferSeconds: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: namespace, Name: "transfer_duration_seconds",
			Help:    "CaptureSession, UploadCapture and RestoreSession duration, with buckets up to 600 s.",
			Buckets: []float64{0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 180, 300, 450, 600},
		}, []string{"method"}),
		nodeReports: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "node_reports_total",
			Help: "Node state reports to the api_server. result: success, rejected (HTTP 4xx), server_error (other HTTP), failed (no reply, or over the caps).",
		}, []string{"result"}),
		nodeReportLast: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: namespace, Name: "node_report_last_success_timestamp_seconds",
			Help: "Unix time of the last node state report that the api_server accepted. 0: none yet.",
		}),
		keyRegs: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "key_registrations_total",
			Help: "Node signing key registrations and refreshes. result: success, rejected (HTTP 4xx), server_error (other HTTP), failed (no reply).",
		}, []string{"result"}),
		keyRegLast: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: namespace, Name: "key_registration_last_success_timestamp_seconds",
			Help: "Unix time of the last successful node signing key registration. 0: none yet.",
		}),
		tplBuilds: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "template_builds_total",
			Help: "Template builds from --rootfs-dir (start-up and BuildTemplate). result: built, existing (a valid template was there), failed.",
		}, []string{"result"}),
		tplBuildSeconds: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: namespace, Name: "template_build_duration_seconds",
			Help:    "Template build duration by result.",
			Buckets: []float64{0.5, 1, 5, 10, 20, 30, 45, 60, 90, 120, 180, 300, 600},
		}, []string{"result"}),
		tplReady: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: namespace, Name: "template_ready",
			Help: "1 if the last template build from --rootfs-dir gave a usable template, else 0.",
		}),
		imageGCRemoved: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace, Name: "image_gc_removed_total",
			Help: "Images that the image GC removed after they were unused for --image-gc-grace. kind: managed, template.",
		}, []string{"kind"}),
	}
	cs := []prometheus.Collector{
		m.createSeconds, m.admissions, m.rpcs, m.rpcSeconds, m.passthrough, m.relayConns, m.guestLog, m.guestDropped,
		m.transferSeconds, m.nodeReports, m.nodeReportLast, m.keyRegs, m.keyRegLast, m.tplBuilds, m.tplBuildSeconds, m.tplReady,
		m.imageGCRemoved,
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
	if transferMethods[method] {
		m.transferSeconds.WithLabelValues(method).Observe(d.Seconds())
	}
}

// PushResult is the result label of a node state report or key
// registration error.
func PushResult(err error) string {
	if err == nil {
		return PushSuccess
	}
	var h interface{ HTTPStatus() int }
	if errors.As(err, &h) {
		if s := h.HTTPStatus(); s >= 400 && s < 500 {
			return PushRejected
		}
		return PushServerError
	}
	return PushFailed
}

// NodeReport records the result of one node state report.
func (m *Metrics) NodeReport(err error) {
	if m == nil {
		return
	}
	m.nodeReports.WithLabelValues(PushResult(err)).Inc()
	if err == nil {
		m.nodeReportLast.SetToCurrentTime()
	}
}

// KeyRegistration records the result of one signing key registration.
func (m *Metrics) KeyRegistration(err error) {
	if m == nil {
		return
	}
	m.keyRegs.WithLabelValues(PushResult(err)).Inc()
	if err == nil {
		m.keyRegLast.SetToCurrentTime()
	}
}

// TemplateBuild records one template build and sets template_ready.
func (m *Metrics) TemplateBuild(d time.Duration, result string) {
	if m == nil {
		return
	}
	m.tplBuilds.WithLabelValues(result).Inc()
	m.tplBuildSeconds.WithLabelValues(result).Observe(d.Seconds())
	m.tplReady.Set(boolFloat(result != TemplateFailed))
}

// ImageGCRemoved counts one image that the image GC removed.
func (m *Metrics) ImageGCRemoved(kind string) {
	if m == nil {
		return
	}
	m.imageGCRemoved.WithLabelValues(kind).Inc()
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
	memPrivate  *prometheus.Desc
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
		src:      src,
		vms:      d("vms", "VMs in the agent's table by state (starting, running, exited).", "state"),
		memTotal: d("node_memory_total_bytes", "Node MemTotal."),
		memAvail: d("node_memory_available_bytes", "Node MemAvailable (the admission input)."),
		diskFree: d("node_disk_free_bytes", "Free space on the data disk."),
		memAlloc: d("vm_memory_allocated_bytes", "Guest memory of the VMs that are not exited."),
		memPrivate: d("vm_memory_private_bytes", "Anonymous memory (smaps_rollup) of the Firecracker processes of the VMs that are not exited: "+
			"the guest pages each VM wrote, plus the VMM's own heap. Page cache of the snapshot memory files is not in it. Balloon free page reporting and the guest's idle reclaim lower it."),
		vcpuAlloc:   d("vm_vcpus_allocated", "vCPUs of the VMs that are not exited."),
		relayOpen:   d("relay_open_connections", "Open egress relay connections."),
		dialOpen:    d("dial_open_streams", "Open Dial streams."),
		statsFailed: d("node_stats_errors", "1 if the last scrape could not read node memory, disk, or the private memory of a VM.", "stat"),
	}
}

func (c *stateCollector) Describe(ch chan<- *prometheus.Desc) {
	for _, d := range []*prometheus.Desc{
		c.vms, c.memTotal, c.memAvail, c.diskFree, c.memAlloc, c.memPrivate, c.vcpuAlloc, c.relayOpen, c.dialOpen, c.statsFailed,
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
		var mem, vcpus, private uint64
		privateFailed := false
		for _, vm := range c.src.VMs() {
			counts[vm.State]++
			if vm.State == pb.VMState_VM_STATE_EXITED {
				continue
			}
			mem += uint64(vm.MemMiB) << 20
			vcpus += uint64(vm.VCPUs)
			if c.src.PrivateMem == nil || vm.PID <= 0 {
				continue
			}
			b, err := c.src.PrivateMem(vm.PID)
			switch {
			case err == nil:
				private += b
			case !errors.Is(err, fs.ErrNotExist) && !errors.Is(err, syscall.ESRCH):
				// A VM that exits during the scrape is not an error.
				privateFailed = true
			}
		}
		// Every state is reported, also at 0, so the series do not vanish.
		for _, s := range []pb.VMState{pb.VMState_VM_STATE_STARTING, pb.VMState_VM_STATE_RUNNING, pb.VMState_VM_STATE_EXITED} {
			gauge(c.vms, float64(counts[s]), stateLabel(s))
		}
		gauge(c.memAlloc, float64(mem))
		gauge(c.vcpuAlloc, float64(vcpus))
		if c.src.PrivateMem != nil {
			// A partial sum would look like reclaimed memory.
			if !privateFailed {
				gauge(c.memPrivate, float64(private))
			}
			gauge(c.statsFailed, boolFloat(privateFailed), "vm_memory")
		}
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
