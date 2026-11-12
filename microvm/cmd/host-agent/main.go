// Command host-agent runs the Firecracker VMs of one Craft node.
//
// It serves the HostAgent gRPC API on a Unix socket. VMs run in a host
// systemd slice and keep running when the agent stops.
package main

import (
	"context"
	"crypto/ed25519"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"math"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"google.golang.org/grpc"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/binaries"
	"github.com/onyx-dot-app/onyx/microvm/internal/egressca"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/imagegc"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	"github.com/onyx-dot-app/onyx/microvm/internal/managed"
	"github.com/onyx-dot-app/onyx/microvm/internal/metrics"
	"github.com/onyx-dot-app/onyx/microvm/internal/nodereport"
	"github.com/onyx-dot-app/onyx/microvm/internal/nodewatch"
	"github.com/onyx-dot-app/onyx/microvm/internal/relay"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/server"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
	"github.com/onyx-dot-app/onyx/microvm/internal/transfer"
)

// version is set with -ldflags "-X main.version=...".
var version = "dev"

// The longest in-chroot socket name the agent uses (the egress relay socket).
const longestSock = "/v.sock_65535"

type flags struct {
	obs            obsFlags
	dataDir        string
	artifactsDir   string
	socket         string
	slice          string
	hostMountNS    bool
	uidBase        uint
	uidCount       uint
	minFreeMemMiB  uint64
	minFreeDiskGB  uint64
	maxScratchGiB  uint
	startTimeout   time.Duration
	stopTimeout    time.Duration
	logLevel       string
	nodeID         string
	egressProxy    string
	apiServerURL   string
	stateReport    time.Duration
	endedRetention time.Duration
	relayIdle      time.Duration
	relayMaxConns  int
	listen         string
	tlsCert        string
	tlsKey         string
	clientCA       string
	dialPorts      string
	clientSANs     string
	dialMax        int
	daemonPort     uint
	rootfsDir      string
	egressCA       string
	egressCACM     string
	tplVCPUs       uint
	tplMemMiB      uint
	tplScratchGiB  uint
	tplKeep        int
	tplTimeout     time.Duration
	managedKeep    int
	managedZipMiB  int64
	managedMaxMiB  int64
	managedFiles   int
	managedBuilds  int
	swapTimeout    time.Duration
	memOverhead    uint
	watchDrain     bool
	drainTaints    string
	drainPoll      time.Duration
	advertise      string
	captureTTL     time.Duration
	captureMax     int64
	transferTO     time.Duration
	transferHTTP   bool
	transferPar    int
	transferPart   int64
	imageGCEvery   time.Duration
	imageGCGrace   time.Duration
}

func main() {
	var f flags
	f.obs.register(flag.CommandLine)
	flag.StringVar(&f.dataDir, "data-dir", "/var/lib/craft-fc", "XFS (reflink) data dir; must be the same path on the host and in the container")
	flag.StringVar(&f.artifactsDir, "artifacts-dir", "/opt/craft-fc", "directory with the firecracker and jailer binaries")
	flag.StringVar(&f.socket, "socket", "", "API Unix socket (default <data-dir>/run/host-agent.sock)")
	flag.StringVar(&f.slice, "slice", "fcvms.slice", "host systemd slice for the VM scopes")
	flag.BoolVar(&f.hostMountNS, "host-mount-ns", true, "start VMs in the host mount namespace (nsenter -t 1 -m); needs hostPID")
	flag.UintVar(&f.uidBase, "uid-base", 1000000, "first jailer UID/GID")
	flag.UintVar(&f.uidCount, "uid-count", 65536, "number of jailer UIDs")
	flag.Uint64Var(&f.minFreeMemMiB, "min-free-mem-mib", 2048, "memory reserve: Create needs MemAvailable >= mem_mib + this")
	flag.Uint64Var(&f.minFreeDiskGB, "min-free-disk-gib", 10, "Create needs this much free space on the data disk")
	flag.UintVar(&f.maxScratchGiB, "max-scratch-gib", 100, "largest scratch disk")
	flag.DurationVar(&f.startTimeout, "start-timeout", 30*time.Second, "limit for one VM start")
	flag.DurationVar(&f.stopTimeout, "stop-timeout", 30*time.Second, "limit for one VM stop")
	flag.StringVar(&f.logLevel, "firecracker-log-level", "Warning", "Firecracker log level")
	flag.StringVar(&f.nodeID, "node-id", os.Getenv("NODE_NAME"), "node name in the signed egress identity (default $NODE_NAME)")
	flag.StringVar(&f.egressProxy, "egress-proxy", "", "sandbox-proxy relay listener host:port; empty turns VM egress off")
	flag.StringVar(&f.apiServerURL, "api-server-url", "", "api_server URL for the node key registration (needs $SANDBOX_NODE_REGISTRATION_SECRET)")
	flag.DurationVar(&f.stateReport, "state-report-interval", nodereport.DefaultInterval, "how often the agent sends its VM state to --api-server-url, signed with the node key (0 = off)")
	flag.DurationVar(&f.endedRetention, "ended-retention", agent.DefaultEndedRetention, "how long each state report lists a VM that exited or stopped (0 = not listed)")
	flag.DurationVar(&f.relayIdle, "relay-idle-timeout", relay.DefaultIdleTimeout, "close a relay connection after this long without traffic (at least 180s)")
	flag.IntVar(&f.relayMaxConns, "relay-max-conns", relay.DefaultMaxConns, "most open relay connections per VM; new ones over the cap are closed")
	flag.StringVar(&f.listen, "listen", "", "mTLS TCP address for the api_server (for example :7443); empty: Unix socket only")
	flag.StringVar(&f.tlsCert, "tls-cert", "", "server certificate file (PEM) for --listen")
	flag.StringVar(&f.tlsKey, "tls-key", "", "server key file (PEM) for --listen")
	flag.StringVar(&f.clientCA, "client-ca", "", "api_server client CA file (PEM); only clients it signed are accepted")
	flag.StringVar(&f.dialPorts, "dial-ports", "3010", "guest vsock ports that Dial allows (never --daemon-port)")
	flag.StringVar(&f.clientSANs, "client-allowed-sans", "", "comma-separated DNS or URI SANs; a client cert must have one (empty: any cert from --client-ca)")
	flag.IntVar(&f.dialMax, "dial-max-streams", server.DefaultMaxDialsPerVM, "most open Dial streams per VM")
	flag.UintVar(&f.daemonPort, "daemon-port", server.DefaultDaemonPort, "guest vsock port of the guest daemon (craft.sandboxd.v1.Sandboxd pass-through)")
	flag.StringVar(&f.rootfsDir, "rootfs-dir", "", "directory with rootfs.ext4 and manifest.json (build-rootfs.sh output); the agent builds its template from it at start and on BuildTemplate. Empty: no build")
	flag.StringVar(&f.egressCA, "egress-ca", "", "egress CA certificate file (PEM) of this deployment, read at each Create (cached 30s) and sent to the guest daemon, which installs it at Init. A root drive with another built-in CA is refused")
	flag.StringVar(&f.egressCACM, "egress-ca-configmap", "", "like --egress-ca, but read from <namespace>/<name>[:<key>] (default key ca.crt) through the Kubernetes API; needs RBAC get on that ConfigMap")
	flag.UintVar(&f.tplVCPUs, "template-vcpus", 2, "vCPUs of the built template (Create must ask for the same)")
	flag.UintVar(&f.tplMemMiB, "template-mem-mib", 4096, "memory of the built template in MiB (Create must ask for the same)")
	flag.UintVar(&f.tplScratchGiB, "template-scratch-gib", 1, "scratch disk of the built template in GiB (Create can grow it)")
	flag.IntVar(&f.tplKeep, "template-keep", 2, "templates to keep; older ones are removed unless a VM uses them")
	flag.DurationVar(&f.tplTimeout, "template-build-timeout", 5*time.Minute, "limit for one template build")
	flag.IntVar(&f.managedKeep, "managed-keep", 3, "managed images to keep; older ones are removed unless a VM has them behind a slot")
	flag.Int64Var(&f.managedZipMiB, "managed-max-zip-mib", managed.DefaultLimits.MaxZipBytes>>20, "largest managed bundle zip")
	flag.Int64Var(&f.managedMaxMiB, "managed-max-mib", managed.DefaultLimits.MaxBytes>>20, "most file content of a managed bundle after unzip (the tmpfs stage size)")
	flag.IntVar(&f.managedFiles, "managed-max-files", managed.DefaultLimits.MaxEntries, "most files and directories in a managed bundle")
	flag.IntVar(&f.managedBuilds, "managed-max-builds", 1, "most managed bundle uploads that receive and build at once")
	flag.DurationVar(&f.swapTimeout, "managed-swap-timeout", 30*time.Second, "limit for the managed drive swap of one VM")
	flag.UintVar(&f.memOverhead, "vm-mem-overhead-mib", jailer.DefaultMemOverheadMiB, "memory each VM scope gets on top of the guest memory (cgroup memory.max = mem_mib + this)")
	flag.BoolVar(&f.watchDrain, "watch-node-drain", false, "read this pod's Node (--node-id) and drain while it has a --drain-taints taint; needs RBAC get on nodes")
	flag.StringVar(&f.drainTaints, "drain-taints", strings.Join(nodewatch.DefaultTaintKeys, ","), "comma-separated taint keys that drain the node")
	flag.DurationVar(&f.drainPoll, "drain-poll-interval", 10*time.Second, "how often --watch-node-drain reads the Node")
	flag.StringVar(&f.advertise, "advertise-address", "", "host:port the api_server dials for --listen, sent with the node key registration (default $POD_IP:<--listen port>)")
	flag.DurationVar(&f.captureTTL, "capture-ttl", server.DefaultCaptureTTL, "delete a spooled session capture that is not uploaded after this long")
	flag.Int64Var(&f.captureMax, "capture-max-bytes", server.DefaultCaptureMaxBytes, "largest session archive (stored bytes) that CaptureSession spools")
	flag.DurationVar(&f.transferTO, "transfer-timeout", 10*time.Minute, "limit for one presigned upload, or for one whole restore download (all range parts)")
	flag.BoolVar(&f.transferHTTP, "transfer-allow-http", false, "allow plain http presigned URLs (test object stores only)")
	flag.IntVar(&f.transferPar, "transfer-parallel", 8, "range GETs at once for a session restore download (1: one plain GET)")
	flag.Int64Var(&f.transferPart, "transfer-part-bytes", 8<<20, "bytes per range GET; a restore holds up to --transfer-parallel of them in memory")
	flag.DurationVar(&f.imageGCEvery, "image-gc-interval", 15*time.Minute, "how often the image GC removes managed images and old templates that no VM used for --image-gc-grace (0 = off)")
	flag.DurationVar(&f.imageGCGrace, "image-gc-grace", 6*time.Hour, "how long a managed image, or a template that is not the current one, stays on the node after no VM uses it")
	flag.Parse()

	log := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	if err := run(f, log); err != nil {
		log.Error("host agent failed", "err", err)
		os.Exit(1)
	}
}

func run(f flags, log *slog.Logger) error {
	if f.socket == "" {
		f.socket = filepath.Join(f.dataDir, "run", "host-agent.sock")
	}
	lay := jailer.Layout{ChrootBase: filepath.Join(f.dataDir, "jail")}
	if err := preflight(f, lay); err != nil {
		return fmt.Errorf("preflight: %w", err)
	}
	bins, err := binaries.Install(f.artifactsDir, filepath.Join(f.dataDir, "bin"),
		binaries.FirecrackerVersion, binaries.FirecrackerSHA256, binaries.JailerSHA256)
	if err != nil {
		return err
	}
	cmd := jailer.Command{
		JailerBin: bins.Jailer, FirecrackerBin: bins.Firecracker, Layout: lay,
		Slice: f.slice, HostMountNS: f.hostMountNS, LogLevel: f.logLevel,
	}
	if err := checkSystemdRun(cmd); err != nil {
		return err
	}
	if err := checkRanges(f); err != nil {
		return err
	}
	if err := checkListen(f); err != nil {
		return err
	}
	kernel, err := binaries.InstallKernel(filepath.Join(f.artifactsDir, "vmlinux"), filepath.Join(f.dataDir, "kernel"))
	if err != nil {
		return err
	}
	caSrc, err := egressCASource(f)
	if err != nil {
		return err
	}
	caFP := ""
	if caSrc != nil {
		// sandbox-proxy writes the CA at its first start, so it can come later.
		cctx, ccancel := context.WithTimeout(context.Background(), 10*time.Second)
		ca, err := caSrc.CA(cctx)
		ccancel()
		if err != nil {
			log.Warn("egress CA not readable yet; Create fails with EGRESS_CA_UNAVAILABLE until it is", "source", caSrc.String(), "err", err)
		} else {
			caFP = ca.Fingerprint
			log.Info("egress CA", "source", caSrc.String(), "sha256", caFP, "subject", ca.Cert.Subject.String(), "not_after", ca.Cert.NotAfter)
		}
	}
	if f.advertise, err = advertiseAddress(f, os.Getenv("POD_IP")); err != nil {
		return err
	}
	uids, err := jailer.NewUIDPool(uint32(f.uidBase), uint32(f.uidCount))
	if err != nil {
		return err
	}
	cgroups, err := fcvm.DetectCgroupView("/proc")
	if err != nil {
		return err
	}
	if cgroups.Private {
		log.Info("private cgroup namespace: VM scopes are checked in the host cgroup tree", "host_cgroup_fs", cgroups.HostCgroupFS)
	}
	launcher := &fcvm.Launcher{Cmd: cmd, Log: log, Cgroups: cgroups, MemOverheadMiB: uint32(f.memOverhead)}
	store := &template.Store{Dir: filepath.Join(f.dataDir, "templates")}
	versions := agent.Versions{
		Firecracker: bins.Version, HostKernel: hostinfo.KernelRelease(), CPUModel: hostinfo.CPUModel(), Agent: version,
		GuestKernel: kernel.Release, GuestKernelSHA256: kernel.SHA256, EgressCAFingerprint: caFP,
		NoEgressCASource: caSrc == nil,
	}
	m := agent.NewManager(agent.Config{
		MinFreeMemMiB:    f.minFreeMemMiB,
		MinFreeDiskBytes: f.minFreeDiskGB * uint64(scratch.GiB),
		MaxScratchGiB:    uint32(f.maxScratchGiB),
		StartTimeout:     f.startTimeout,
		StopTimeout:      f.stopTimeout,
		TombstoneTTL:     24 * time.Hour,
		EndedRetention:   f.endedRetention,
	},
		store,
		launcher,
		hostinfo.Stats{DataDir: f.dataDir},
		uids,
		versions,
		log,
	)
	m.UseJournal(&journal.Journal{Dir: filepath.Join(f.dataDir, "journal")})
	if err := m.UseDrainFile(filepath.Join(f.dataDir, "drain.json")); err != nil {
		return err
	}
	if f.daemonPort == 0 || f.daemonPort > math.MaxUint32 {
		return fmt.Errorf("--daemon-port %d is not a vsock port", f.daemonPort)
	}
	// Registered before Recover, so a VM that exits after adoption also
	// drops its daemon connection before its socket and UID are freed.
	pt := server.NewPassthrough(m, uint32(f.daemonPort), log)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	push, err := setupEgress(f, m, log)
	if err != nil {
		return err
	}
	obs, err := newObservability(f.obs, m, lay, hostinfo.Stats{DataDir: f.dataDir}, log)
	if err != nil {
		return err
	}
	push.start(ctx, obs.metrics)
	drainWatch, err := startDrainWatch(ctx, f, m, log)
	if err != nil {
		return err
	}
	t0 := time.Now()
	rep, err := m.Recover(context.Background(), launcher)
	if err != nil {
		return err
	}
	log.Info("recovered VMs", "adopted", rep.Adopted, "unresponsive", rep.Unresponsive, "exited", rep.Exited,
		"abandoned", rep.Abandoned, "unverified", rep.Unverified, "unreadable", rep.Unreadable,
		"tombstones", rep.Tombstones, "orphans_killed", rep.Orphans, "leftovers_removed", rep.Leftovers,
		"ms", time.Since(t0).Milliseconds())
	ports, err := parsePorts(f.dialPorts)
	if err != nil {
		return err
	}
	builder := &tplbuild.Builder{
		Store: store, VMM: tplbuild.FirecrackerVMM{Launcher: launcher}, Slots: m, Node: versions.NodeKey(),
		GuestKernel: kernel.Release, KernelPath: kernel.Path,
		VCPUs: uint32(f.tplVCPUs), MemMiB: uint32(f.tplMemMiB), ScratchGiB: uint32(f.tplScratchGiB),
		Keep: f.tplKeep, Ready: tplbuild.DaemonHealth(uint32(f.daemonPort)), Timeout: f.tplTimeout, Log: log,
	}
	if err := builder.CleanStaging(); err != nil {
		return err
	}
	mstore := &managed.Store{
		Dir: filepath.Join(f.dataDir, "managed"), Stager: managed.TmpfsStager{}, Log: log,
		Limits:    managed.Limits{MaxZipBytes: f.managedZipMiB << 20, MaxBytes: f.managedMaxMiB << 20, MaxEntries: f.managedFiles},
		MaxBuilds: f.managedBuilds,
	}
	if err := mstore.CleanStaging(managed.Unmount); err != nil {
		return err
	}
	stats := hostinfo.Stats{DataDir: f.dataDir}
	saves, err := server.NewSaves(&server.Saves{
		M: m, PT: pt, Dir: filepath.Join(f.dataDir, "captures"), TTL: f.captureTTL, MaxBytes: f.captureMax,
		MinFreeBytes: f.minFreeDiskGB * uint64(scratch.GiB), FreeBytes: stats.DiskFreeBytes,
		Transfer: &transfer.Client{Timeout: f.transferTO, AllowHTTP: f.transferHTTP, Parallel: f.transferPar, PartBytes: f.transferPart},
		Log:      log,
	})
	if err != nil {
		return fmt.Errorf("capture spool: %w", err)
	}
	m.UseManagedGuest(server.DaemonManaged{Port: uint32(f.daemonPort)}, f.swapTimeout)
	svc := &server.Service{M: m, DialPorts: ports, DaemonPort: uint32(f.daemonPort), MaxDialsPerVM: f.dialMax, Keys: pt, Managed: &server.ManagedImages{Store: mstore, Keep: f.managedKeep}, Saves: saves, Log: log}
	if caSrc != nil {
		svc.EgressCA = &egressca.Cached{Src: caSrc, TTL: egressCACacheTTL, MaxAge: egressCAMaxAge}
	} else {
		log.Warn("no --egress-ca or --egress-ca-configmap: VMs trust only a CA built into the root drive")
	}
	// The template of the last build from --rootfs-dir; the image GC keeps it.
	var currentTemplate atomic.Pointer[string]
	// Held over the build and its metrics, so template_ready shows the last
	// build to finish, and over each template GC removal, so a build's
	// template is current before the GC can see it unused.
	var buildMu sync.Mutex
	if f.rootfsDir != "" {
		svc.Builder = func(ctx context.Context) (tplbuild.Result, error) {
			buildMu.Lock()
			defer buildMu.Unlock()
			t0 := time.Now()
			r, err := buildTemplate(ctx, builder, f.rootfsDir)
			obs.metrics.TemplateBuild(time.Since(t0), templateResult(r, err))
			if r.Template != nil {
				v := r.Template.Version
				currentTemplate.Store(&v)
			}
			return r, err
		}
	}
	if gc := imageGC(f, m, store, mstore, &currentTemplate, &buildMu, obs.metrics, log); gc != nil {
		go gc.Run(ctx)
	}
	if err := obs.start(ctx, svc); err != nil {
		return err
	}
	ln, err := server.ListenUnix(f.socket)
	if err != nil {
		return err
	}
	// Both listeners serve the HostAgent API and the daemon pass-through.
	servers := []*grpc.Server{server.NewServer(svc, append(pt.ServerOptions(), obs.serverOptions()...)...)}
	listeners := []net.Listener{ln}
	if f.listen != "" {
		creds, err := (&server.MTLS{
			CertFile: f.tlsCert, KeyFile: f.tlsKey, ClientCAFile: f.clientCA, AllowedSANs: splitList(f.clientSANs),
		}).Credentials()
		if err != nil {
			return err
		}
		tln, err := net.Listen("tcp", f.listen)
		if err != nil {
			return err
		}
		servers = append(servers, server.NewServer(svc, append(append(pt.ServerOptions(), obs.serverOptions()...), grpc.Creds(creds))...))
		listeners = append(listeners, tln)
	}
	go func() {
		<-ctx.Done()
		var refresh func(context.Context)
		if drainWatch != nil {
			refresh = drainWatch.Once
		}
		push.leave(m.DrainTaints, refresh, log)
		// VMs keep running: they are in the host slice, not in this process.
		for _, s := range servers {
			s.GracefulStop()
		}
	}()
	log.Info("host agent ready", "socket", f.socket, "listen", f.listen, "dial_ports", ports, "daemon_port", f.daemonPort,
		"firecracker", bins.Version, "version", version)
	errs := make(chan error, len(servers))
	for i := range servers {
		go func(i int) { errs <- servers[i].Serve(listeners[i]) }(i)
	}
	go startupTemplates(svc, builder, log)
	return <-errs
}

func buildTemplate(ctx context.Context, b *tplbuild.Builder, rootfsDir string) (tplbuild.Result, error) {
	rf, err := tplbuild.LoadRootfs(rootfsDir)
	if err != nil {
		return tplbuild.Result{}, err
	}
	// A build goes on when its caller goes away.
	return b.Build(context.WithoutCancel(ctx), rf)
}

// templateResult is the metrics result of a build. A build that made a
// template but then failed its GC still gave a usable template.
func templateResult(r tplbuild.Result, err error) string {
	switch {
	case r.Template == nil:
		return metrics.TemplateFailed
	case r.Built:
		return metrics.TemplateBuilt
	default:
		return metrics.TemplateExisting
	}
}

// startupTemplates builds the template from --rootfs-dir, or only removes
// old templates when there is no root drive.
func startupTemplates(svc *server.Service, b *tplbuild.Builder, log *slog.Logger) {
	if svc.Builder == nil {
		if removed, err := b.Store.GC(b.Keep, b.Slots.TemplatesInUse); err != nil {
			log.Error("template GC", "err", err)
		} else if len(removed) > 0 {
			log.Info("template GC", "removed", removed)
		}
		return
	}
	r, err := svc.Builder(context.Background())
	if err != nil {
		log.Error("template build at start-up failed", "err", err)
		return
	}
	log.Info("template ready", "template", r.Template.Version, "built", r.Built, "build_ms", r.BuildMS, "removed", r.Removed)
}

// imageGC returns the sweeper of unused managed images and old templates,
// or nil with --image-gc-interval 0. Templates are swept only once a build
// from --rootfs-dir named the current template.
func imageGC(f flags, m *agent.Manager, store *template.Store, mstore *managed.Store,
	current *atomic.Pointer[string], buildMu sync.Locker, mt *metrics.Metrics, log *slog.Logger) *imagegc.Sweeper {
	if f.imageGCEvery <= 0 {
		log.Warn("--image-gc-interval is 0: unused managed images and old templates stay on the node")
		return nil
	}
	return &imagegc.Sweeper{
		Grace: f.imageGCGrace, Interval: f.imageGCEvery, Log: log, Removed: mt.ImageGCRemoved,
		Kinds: []imagegc.Kind{
			{
				Name: "managed",
				List: func() ([]string, error) {
					imgs, err := mstore.List()
					ids := make([]string, 0, len(imgs))
					for _, img := range imgs {
						ids = append(ids, img.ID)
					}
					return ids, err
				},
				Keep:   m.ManagedImagesInUse,
				Remove: func(id string) (bool, error) { return mstore.RemoveUnused(id, m.ManagedImagesInUse) },
			},
			templateKind(store, m.TemplatesInUse, current, buildMu),
		},
	}
}

// templateKind sweeps the templates other than the current one. It lists
// nothing until a build named the current template. Removals hold buildMu.
func templateKind(store *template.Store, inUse func() map[string]bool, current *atomic.Pointer[string], buildMu sync.Locker) imagegc.Kind {
	kept := func() map[string]bool {
		keep := inUse()
		if c := current.Load(); c != nil {
			keep[*c] = true
		}
		return keep
	}
	return imagegc.Kind{
		Name: "template",
		List: func() ([]string, error) {
			if current.Load() == nil {
				return nil, nil
			}
			ts, err := store.List()
			ids := make([]string, 0, len(ts))
			for _, t := range ts {
				ids = append(ids, t.Version)
			}
			return ids, err
		},
		Keep: kept,
		Remove: func(id string) (bool, error) {
			buildMu.Lock()
			defer buildMu.Unlock()
			return store.RemoveUnused(id, kept)
		},
	}
}

// egressCACacheTTL is how long Create reuses a CA read. A rotated CA reaches
// new VMs after at most this long.
const egressCACacheTTL = 30 * time.Second

// egressCAMaxAge is how long Create uses the last good CA while reads fail.
const egressCAMaxAge = time.Hour

// egressCASource returns the --egress-ca or --egress-ca-configmap source, or
// nil if neither is set.
func egressCASource(f flags) (egressca.Source, error) {
	switch {
	case f.egressCA != "" && f.egressCACM != "":
		return nil, errors.New("set --egress-ca or --egress-ca-configmap, not both")
	case f.egressCA != "":
		return egressca.File{Path: f.egressCA}, nil
	case f.egressCACM != "":
		ns, name, key, err := egressca.ParseConfigMapRef(f.egressCACM)
		if err != nil {
			return nil, fmt.Errorf("--egress-ca-configmap: %w", err)
		}
		c, err := nodewatch.NewInCluster(f.nodeID)
		if err != nil {
			return nil, fmt.Errorf("--egress-ca-configmap: %w", err)
		}
		return egressca.ConfigMap{Getter: c, Namespace: ns, Name: name, Key: key}, nil
	}
	return nil, nil
}

func parsePorts(s string) ([]uint32, error) {
	var out []uint32
	for _, p := range strings.Split(s, ",") {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		n, err := strconv.ParseUint(p, 10, 32)
		if err != nil || n == 0 {
			return nil, fmt.Errorf("bad --dial-ports entry %q", p)
		}
		out = append(out, uint32(n))
	}
	if len(out) == 0 {
		// An empty list would fall back to the default ports.
		return nil, fmt.Errorf("--dial-ports %q names no port", s)
	}
	return out, nil
}

// startDrainWatch reads the agent's Node every --drain-poll-interval and
// drains the node while it has a drain taint. The first read
// runs before the API serves, so a restarted agent on a cordoned node
// never admits a VM.
func startDrainWatch(ctx context.Context, f flags, m *agent.Manager, log *slog.Logger) (*nodewatch.Watcher, error) {
	if !f.watchDrain {
		return nil, nil
	}
	keys := splitList(f.drainTaints)
	if len(keys) == 0 {
		return nil, errors.New("--watch-node-drain needs --drain-taints")
	}
	if f.drainPoll < time.Second {
		return nil, fmt.Errorf("--drain-poll-interval %v must be at least 1s", f.drainPoll)
	}
	src, err := nodewatch.NewInCluster(f.nodeID)
	if err != nil {
		return nil, fmt.Errorf("--watch-node-drain: %w", err)
	}
	w := &nodewatch.Watcher{Source: src, Keys: keys, Interval: f.drainPoll, Timeout: 10 * time.Second, Apply: m.SetNodeDrain}
	w.Once(ctx)
	go w.Run(ctx)
	log.Info("watching the node for drain taints", "node", f.nodeID, "taints", keys, "interval", f.drainPoll)
	return w, nil
}

// pushers are the key registration and node state report loops. They
// start after the metrics exist, so the first result is counted.
type pushers struct {
	reg *relay.Registrar
	rep *nodereport.Reporter
	// deregister ends the node's registration; nil without a registrar.
	deregister func(context.Context) (bool, error)
	wg         *sync.WaitGroup
}

func (p pushers) start(ctx context.Context, mt *metrics.Metrics) {
	wg := p.wg
	if wg == nil {
		wg = &sync.WaitGroup{}
	}
	if p.reg != nil {
		p.reg.Observe = mt.KeyRegistration
		wg.Go(func() { p.reg.Run(ctx) })
	}
	if p.rep != nil {
		p.rep.Observe = mt.NodeReport
		wg.Go(func() { p.rep.Run(ctx) })
	}
}

// refreshTimeout and deregisterTimeout bound the node read and the
// deregistration at shutdown, well inside the pod's termination grace period.
const (
	refreshTimeout    = 3 * time.Second
	deregisterTimeout = 5 * time.Second
)

// leave runs after the stop signal. On a node with drain taints (the node
// goes away) it ends the node's registration, so placement and the node
// list drop the node at once. Else, or if the call fails, the registration
// expires after relay.KeyTTL.
// refresh, if set, reads the node again first: the taint can be newer than
// the last poll.
func (p pushers) leave(taints func() []string, refresh func(context.Context), log *slog.Logger) {
	if p.deregister == nil {
		return
	}
	// A registration that is still in flight must not come after the
	// deregistration.
	p.wg.Wait()
	if refresh != nil {
		rctx, rcancel := context.WithTimeout(context.Background(), refreshTimeout)
		refresh(rctx)
		rcancel()
	}
	t := taints()
	if len(t) == 0 {
		log.Info("agent stops on a node without drain taints; the node stays registered")
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), deregisterTimeout)
	defer cancel()
	ok, err := p.deregister(ctx)
	if err != nil {
		log.Error("node deregistration failed; the registration expires on its own", "taints", t, "err", err)
		return
	}
	log.Info("node deregistered", "taints", t, "deregistered", ok)
}

// setupEgress makes a fresh node signing key and attaches the relay to the
// Manager. Its pushers keep the key registered with the api_server and send
// the node state reports.
func setupEgress(f flags, m *agent.Manager, log *slog.Logger) (pushers, error) {
	if f.egressProxy == "" {
		log.Warn("no --egress-proxy: VMs have no egress")
		return pushers{}, nil
	}
	if f.nodeID == "" {
		return pushers{}, errors.New("--egress-proxy needs --node-id (or $NODE_NAME)")
	}
	if f.relayMaxConns < 1 {
		return pushers{}, fmt.Errorf("--relay-max-conns %d must be 1 or more", f.relayMaxConns)
	}
	_, key, err := ed25519.GenerateKey(nil)
	if err != nil {
		return pushers{}, err
	}
	kid, err := relay.NewKeyID(f.nodeID, time.Now())
	if err != nil {
		return pushers{}, err
	}
	signer := relay.NewSigner(f.nodeID, kid, key)
	m.UseEgress(&relay.AgentEgress{Relay: &relay.Relay{
		Signer: signer, Upstream: f.egressProxy, IdleTimeout: f.relayIdle, MaxConns: f.relayMaxConns, Log: log,
	}})
	if f.apiServerURL == "" {
		log.Warn("no --api-server-url: the node signing key is not registered, so the proxy rejects VM egress")
		return pushers{}, nil
	}
	secret := os.Getenv("SANDBOX_NODE_REGISTRATION_SECRET")
	if secret == "" {
		return pushers{}, errors.New("--api-server-url needs $SANDBOX_NODE_REGISTRATION_SECRET")
	}
	if f.advertise == "" {
		log.Warn("no --advertise-address and no $POD_IP: the registration has no agent address, so the api_server cannot place VMs here")
	}
	g := &relay.Registrar{BaseURL: f.apiServerURL, Secret: secret, Signer: signer, AgentAddress: f.advertise, Log: log}
	p := pushers{reg: g, wg: &sync.WaitGroup{}, deregister: func(ctx context.Context) (bool, error) {
		return nodereport.Deregister(ctx, nil, f.apiServerURL, signer)
	}}
	if f.stateReport <= 0 {
		log.Warn("--state-report-interval is 0: the api_server does not reconcile this node's VMs")
		return p, nil
	}
	r := &nodereport.Reporter{
		BaseURL: f.apiServerURL, Signer: signer, List: func() []nodereport.VM { return reportVMs(m.List()) },
		Ended: func() []nodereport.EndedVM { return reportEnded(m.Ended()) },
		Ready: g.Registered(), Log: log, Interval: f.stateReport,
	}
	p.rep = r
	return p, nil
}

// reportVMs converts the Manager's List for the node state report.
func reportVMs(vms []agent.VM) []nodereport.VM {
	out := make([]nodereport.VM, 0, len(vms))
	for _, vm := range vms {
		v := nodereport.VM{
			SandboxID: vm.SandboxID, TenantID: vm.TenantID, Attempt: vm.Attempt, Generation: vm.Generation,
			State: strings.TrimPrefix(vm.State.String(), "VM_STATE_"), Template: vm.Template,
			VCPUs: vm.VCPUs, MemMiB: vm.MemMiB, ScratchGiB: vm.ScratchGiB, PID: vm.PID,
		}
		if !vm.StartedAt.IsZero() {
			t := vm.StartedAt.UTC()
			v.StartedAt = &t
		}
		out = append(out, v)
	}
	return out
}

// reportEnded converts the Manager's ended list for the node state report.
func reportEnded(ended []agent.EndedVM) []nodereport.EndedVM {
	out := make([]nodereport.EndedVM, 0, len(ended))
	for _, e := range ended {
		out = append(out, nodereport.EndedVM{
			SandboxID: e.SandboxID, TenantID: e.TenantID, Attempt: e.Attempt, Generation: e.Generation,
			Reason: string(e.Reason), EndedAt: e.EndedAt.UTC(),
		})
	}
	return out
}

func preflight(f flags, lay jailer.Layout) error {
	if os.Geteuid() != 0 {
		return errors.New("the host agent must run as root")
	}
	if _, err := os.Stat("/dev/kvm"); err != nil {
		return fmt.Errorf("no /dev/kvm: %w", err)
	}
	if _, err := os.Stat("/sys/fs/cgroup/cgroup.controllers"); err != nil {
		return fmt.Errorf("cgroup v2 is not mounted at /sys/fs/cgroup: %w", err)
	}
	for _, d := range []string{"templates", "jail", "bin", "kernel", "run", "journal", "managed"} {
		if err := os.MkdirAll(filepath.Join(f.dataDir, d), 0o700); err != nil {
			return err
		}
	}
	// The jailer needs to traverse the chroot base as the VM user.
	if err := os.Chmod(lay.ChrootBase, 0o711); err != nil {
		return err
	}
	if err := scratch.ProbeReflink(f.dataDir); err != nil {
		return fmt.Errorf("data dir %s: %w", f.dataDir, err)
	}
	longest := lay.HostPath(strings.Repeat("x", 36), longestSock)
	if len(longest) > jailer.MaxSockPath {
		return fmt.Errorf("data dir %s is too long: VM socket paths would be %d bytes, the limit is %d",
			f.dataDir, len(longest), jailer.MaxSockPath)
	}
	return nil
}

// checkRanges rejects flag values that do not fit the uint32 fields.
func checkRanges(f flags) error {
	if f.uidBase == 0 || f.uidCount == 0 || uint64(f.uidBase)+uint64(f.uidCount) > math.MaxUint32 {
		return fmt.Errorf("--uid-base %d and --uid-count %d must be more than 0 and end at or below %d",
			f.uidBase, f.uidCount, uint64(math.MaxUint32))
	}
	if f.tplVCPUs == 0 || f.tplVCPUs > 32 || f.tplMemMiB < 128 || f.tplMemMiB > math.MaxUint32 ||
		f.tplScratchGiB == 0 || f.tplScratchGiB > f.maxScratchGiB || f.tplKeep < 1 {
		return fmt.Errorf("bad template shape --template-vcpus %d --template-mem-mib %d --template-scratch-gib %d --template-keep %d",
			f.tplVCPUs, f.tplMemMiB, f.tplScratchGiB, f.tplKeep)
	}
	if f.managedKeep < 1 || f.managedZipMiB < 1 || f.managedMaxMiB < 1 || f.managedFiles < 1 || f.managedBuilds < 1 || f.swapTimeout <= 0 {
		return fmt.Errorf("bad managed limits --managed-keep %d --managed-max-zip-mib %d --managed-max-mib %d --managed-max-files %d --managed-max-builds %d --managed-swap-timeout %v",
			f.managedKeep, f.managedZipMiB, f.managedMaxMiB, f.managedFiles, f.managedBuilds, f.swapTimeout)
	}
	if f.transferPar < 1 || f.transferPar > 64 || f.transferPart < 1<<20 || f.transferPart > 256<<20 {
		return fmt.Errorf("bad transfer settings --transfer-parallel %d (1 to 64) --transfer-part-bytes %d (1 MiB to 256 MiB)",
			f.transferPar, f.transferPart)
	}
	if f.imageGCEvery < 0 || (f.imageGCEvery > 0 && (f.imageGCEvery < time.Minute || f.imageGCGrace < 10*time.Minute)) {
		return fmt.Errorf("--image-gc-interval %v must be 0 or at least 1m, and --image-gc-grace %v at least 10m",
			f.imageGCEvery, f.imageGCGrace)
	}
	if f.memOverhead < 16 || f.memOverhead > 4096 {
		return fmt.Errorf("--vm-mem-overhead-mib %d must be 16 to 4096", f.memOverhead)
	}
	if f.maxScratchGiB > math.MaxUint32 {
		return fmt.Errorf("--max-scratch-gib %d is too large", f.maxScratchGiB)
	}
	return nil
}

// checkListen rejects a TCP listener without its TLS files, TLS flags
// without a listener, and a Dial cap under 1.
func checkListen(f flags) error {
	tls := f.tlsCert != "" || f.tlsKey != "" || f.clientCA != "" || f.clientSANs != ""
	if f.listen == "" && tls {
		return errors.New("--tls-cert, --tls-key, --client-ca and --client-allowed-sans need --listen")
	}
	if f.listen != "" && (f.tlsCert == "" || f.tlsKey == "" || f.clientCA == "") {
		return errors.New("--listen needs --tls-cert, --tls-key and --client-ca")
	}
	if f.dialMax < 1 {
		return fmt.Errorf("--dial-max-streams %d must be 1 or more", f.dialMax)
	}
	return nil
}

// dnsHost matches the DNS names the api_server accepts in agent_address.
var dnsHost = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9.-]*$`)

// advertiseAddress is the host:port of --listen that the api_server dials:
// --advertise-address, else $POD_IP with the --listen port, else a specific
// --listen host. Empty if there is no TCP listener or no usable host.
func advertiseAddress(f flags, podIP string) (string, error) {
	if f.listen == "" {
		if f.advertise != "" {
			return "", errors.New("--advertise-address needs --listen")
		}
		return "", nil
	}
	if f.advertise != "" {
		host, port, err := net.SplitHostPort(f.advertise)
		if err != nil || (net.ParseIP(host) == nil && !dnsHost.MatchString(host)) {
			return "", fmt.Errorf("--advertise-address %q must be host:port with a DNS name or IP address", f.advertise)
		}
		if !canonicalPort(port) {
			return "", fmt.Errorf("--advertise-address %q has a bad port", f.advertise)
		}
		return f.advertise, nil
	}
	host, port, err := net.SplitHostPort(f.listen)
	if err != nil {
		return "", fmt.Errorf("--listen %q: %w", f.listen, err)
	}
	if !canonicalPort(port) {
		return "", fmt.Errorf("--listen %q needs a port from 1 to 65535 in plain decimal", f.listen)
	}
	if podIP != "" {
		if net.ParseIP(podIP) == nil {
			return "", fmt.Errorf("$POD_IP %q is not an IP address", podIP)
		}
		return net.JoinHostPort(podIP, port), nil
	}
	if ip := net.ParseIP(host); host == "" || (ip != nil && ip.IsUnspecified()) {
		return "", nil
	}
	return net.JoinHostPort(host, port), nil
}

// canonicalPort reports a port in 1-65535 in plain decimal, the form the
// api_server accepts in agent_address.
func canonicalPort(port string) bool {
	n, err := strconv.ParseUint(port, 10, 16)
	return err == nil && n != 0 && strconv.FormatUint(n, 10) == port
}

func splitList(s string) []string {
	var out []string
	for _, v := range strings.Split(s, ",") {
		if v = strings.TrimSpace(v); v != "" {
			out = append(out, v)
		}
	}
	return out
}

func checkSystemdRun(c jailer.Command) error {
	argv := []string{"systemd-run", "--version"}
	if c.HostMountNS {
		argv = append([]string{"nsenter", "-t", "1", "-m", "--"}, argv...)
	}
	if out, err := exec.Command(argv[0], argv[1:]...).CombinedOutput(); err != nil {
		return fmt.Errorf("%s: %w: %s", strings.Join(argv, " "), err, strings.TrimSpace(string(out)))
	}
	return nil
}
