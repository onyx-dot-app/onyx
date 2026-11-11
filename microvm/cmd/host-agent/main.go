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
	"syscall"
	"time"

	"google.golang.org/grpc"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/binaries"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	"github.com/onyx-dot-app/onyx/microvm/internal/managed"
	"github.com/onyx-dot-app/onyx/microvm/internal/nodewatch"
	"github.com/onyx-dot-app/onyx/microvm/internal/relay"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/server"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
)

// version is set with -ldflags "-X main.version=...".
var version = "dev"

// The longest in-chroot socket name the agent uses (the egress relay socket).
const longestSock = "/v.sock_65535"

type flags struct {
	obs           obsFlags
	dataDir       string
	artifactsDir  string
	socket        string
	slice         string
	hostMountNS   bool
	uidBase       uint
	uidCount      uint
	minFreeMemMiB uint64
	minFreeDiskGB uint64
	maxScratchGiB uint
	startTimeout  time.Duration
	stopTimeout   time.Duration
	logLevel      string
	nodeID        string
	egressProxy   string
	apiServerURL  string
	relayIdle     time.Duration
	relayMaxConns int
	listen        string
	tlsCert       string
	tlsKey        string
	clientCA      string
	dialPorts     string
	clientSANs    string
	dialMax       int
	daemonPort    uint
	rootfsDir     string
	egressCA      string
	tplVCPUs      uint
	tplMemMiB     uint
	tplScratchGiB uint
	tplKeep       int
	tplTimeout    time.Duration
	managedKeep   int
	managedZipMiB int64
	managedMaxMiB int64
	managedFiles  int
	managedBuilds int
	swapTimeout   time.Duration
	memOverhead   uint
	watchDrain    bool
	drainTaints   string
	drainPoll     time.Duration
	advertise     string
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
	flag.StringVar(&f.egressCA, "egress-ca", "", "egress CA certificate (PEM) of this deployment; templates whose root drive trusts another CA are refused. Empty: not checked")
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
	caFP := ""
	if f.egressCA != "" {
		if caFP, err = tplbuild.CAFileFingerprint(f.egressCA); err != nil {
			return fmt.Errorf("--egress-ca: %w", err)
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
	}
	m := agent.NewManager(agent.Config{
		MinFreeMemMiB:    f.minFreeMemMiB,
		MinFreeDiskBytes: f.minFreeDiskGB * uint64(scratch.GiB),
		MaxScratchGiB:    uint32(f.maxScratchGiB),
		StartTimeout:     f.startTimeout,
		StopTimeout:      f.stopTimeout,
		TombstoneTTL:     24 * time.Hour,
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
	if err := setupEgress(ctx, f, m, log); err != nil {
		return err
	}
	if err := startDrainWatch(ctx, f, m, log); err != nil {
		return err
	}
	obs, err := newObservability(f.obs, m, lay, hostinfo.Stats{DataDir: f.dataDir}, log)
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
	m.UseManagedGuest(server.DaemonManaged{Port: uint32(f.daemonPort)}, f.swapTimeout)
	svc := &server.Service{M: m, DialPorts: ports, DaemonPort: uint32(f.daemonPort), MaxDialsPerVM: f.dialMax, Keys: pt, Managed: &server.ManagedImages{Store: mstore, Keep: f.managedKeep}, Log: log}
	if f.rootfsDir != "" {
		svc.Builder = func(ctx context.Context) (tplbuild.Result, error) {
			rf, err := tplbuild.LoadRootfs(f.rootfsDir)
			if err != nil {
				return tplbuild.Result{}, err
			}
			// A build goes on when its caller goes away.
			return builder.Build(context.WithoutCancel(ctx), rf)
		}
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
// drains the node while it has a drain taint (ENG-4569). The first read
// runs before the API serves, so a restarted agent on a cordoned node
// never admits a VM.
func startDrainWatch(ctx context.Context, f flags, m *agent.Manager, log *slog.Logger) error {
	if !f.watchDrain {
		return nil
	}
	keys := splitList(f.drainTaints)
	if len(keys) == 0 {
		return errors.New("--watch-node-drain needs --drain-taints")
	}
	if f.drainPoll < time.Second {
		return fmt.Errorf("--drain-poll-interval %v must be at least 1s", f.drainPoll)
	}
	src, err := nodewatch.NewInCluster(f.nodeID)
	if err != nil {
		return fmt.Errorf("--watch-node-drain: %w", err)
	}
	w := &nodewatch.Watcher{Source: src, Keys: keys, Interval: f.drainPoll, Timeout: 10 * time.Second, Apply: m.SetNodeDrain}
	w.Once(ctx)
	go w.Run(ctx)
	log.Info("watching the node for drain taints", "node", f.nodeID, "taints", keys, "interval", f.drainPoll)
	return nil
}

// setupEgress makes a fresh node signing key, attaches the relay to the
// Manager and keeps the key registered with the api_server.
func setupEgress(ctx context.Context, f flags, m *agent.Manager, log *slog.Logger) error {
	if f.egressProxy == "" {
		log.Warn("no --egress-proxy: VMs have no egress")
		return nil
	}
	if f.nodeID == "" {
		return errors.New("--egress-proxy needs --node-id (or $NODE_NAME)")
	}
	if f.relayMaxConns < 1 {
		return fmt.Errorf("--relay-max-conns %d must be 1 or more", f.relayMaxConns)
	}
	_, key, err := ed25519.GenerateKey(nil)
	if err != nil {
		return err
	}
	kid, err := relay.NewKeyID(f.nodeID, time.Now())
	if err != nil {
		return err
	}
	signer := relay.NewSigner(f.nodeID, kid, key)
	m.UseEgress(&relay.AgentEgress{Relay: &relay.Relay{
		Signer: signer, Upstream: f.egressProxy, IdleTimeout: f.relayIdle, MaxConns: f.relayMaxConns, Log: log,
	}})
	if f.apiServerURL == "" {
		log.Warn("no --api-server-url: the node signing key is not registered, so the proxy rejects VM egress")
		return nil
	}
	secret := os.Getenv("SANDBOX_NODE_REGISTRATION_SECRET")
	if secret == "" {
		return errors.New("--api-server-url needs $SANDBOX_NODE_REGISTRATION_SECRET")
	}
	if f.advertise == "" {
		log.Warn("no --advertise-address and no $POD_IP: the registration has no agent address, so the api_server cannot place VMs here")
	}
	g := &relay.Registrar{BaseURL: f.apiServerURL, Secret: secret, Signer: signer, AgentAddress: f.advertise, Log: log}
	go g.Run(ctx)
	return nil
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
