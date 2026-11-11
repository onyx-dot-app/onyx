// Command guest-daemon is the Sandboxd gRPC server inside each Craft
// micro-VM. It listens on vsock and runs commands as root, each in its own
// cgroup. It is not PID 1: the VM init starts it and restarts it.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"maps"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/klauspost/compress/zstd"
	"google.golang.org/grpc"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/sysops"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/vsock"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// windowBytes is the HTTP/2 flow-control window of the gRPC server.
const windowBytes = 16 << 20

// version is set with -ldflags "-X main.version=...".
var version = "dev"

func main() {
	port := flag.Uint("port", 52, "vsock port")
	listen := flag.String("listen", "", "listen on unix:<path> instead of vsock (tests); there is no TCP listener")
	cgroupRoot := flag.String("cgroup-root", "/sys/fs/cgroup/guestd", "cgroup v2 dir for the executions; empty uses process groups")
	stateFile := flag.String("state-file", "/run/craft-fc/guest-daemon-init.json", "Init state, kept across daemon restarts; empty keeps it in memory")
	attachCmd := flag.String("attach-cmd", "/craft-fc/lib/attach", "drive attach script that Init runs; empty to skip")
	relayPIDFile := flag.String("relay-pidfile", "/run/craft-fc/egress-relay.pid", "egress relay PID file; Init sends it SIGHUP; empty to skip")
	growMounts := flag.String("grow-fs", "/mnt/scratch", "comma-separated ext4 mount points that Init grows; empty for none")
	defDeadline := flag.Duration("default-deadline", 30*time.Minute, "command deadline when the call sets none")
	maxDeadline := flag.Duration("max-deadline", 24*time.Hour, "largest command deadline")
	outBytes := flag.Int("output-bytes", 4<<20, "output bytes kept per stream and execution")
	outBudget := flag.Int64("output-budget", 256<<20, "output bytes kept by all executions; over it, ended ones lose their output first")
	maxRunning := flag.Int("max-running", 64, "most running executions")
	logLevel := flag.String("log-level", "info", "debug, info, warn or error")
	managedMnt := flag.String("managed-mount", "/workspace/managed", "mount point of the managed drive; empty turns MountManaged off")
	managedA := flag.String("managed-dev-a", "/dev/vdc", "managed slot A device (the image's MANAGED_DEV)")
	managedB := flag.String("managed-dev-b", "/dev/vdf", "managed slot B device (the image's MANAGED_DEV_B)")
	reportOrder := flag.Int("page-reporting-order", 0, "balloon free page reporting order to set at start (0 reports every free page); -1 leaves the kernel default")
	reclaimIdle := flag.Duration("reclaim-idle", 5*time.Minute, "drop the page cache after this long without daemon calls (Health does not count); 0 turns it off")
	caAnchor := flag.String("ca-anchor", sysops.DefaultCAPaths.Anchor, "egress CA file that update-ca-certificates reads")
	caBundle := flag.String("ca-bundle", sysops.DefaultCAPaths.Bundle, "system CA bundle that Init adds the SetKey egress CA to; empty turns the CA install off")
	caNSSDB := flag.String("ca-nssdb", sysops.DefaultCAPaths.NSSDB, "NSS database (Chromium) that gets the egress CA; certutil runs as its owner; empty to skip")
	certutil := flag.String("certutil", sysops.DefaultCAPaths.Certutil, "NSS certutil program")
	var fc files.Config
	flag.StringVar(&fc.SessionsRoot, "sessions-root", files.DefaultSessionsRoot, "directory with one directory per session (file calls, capture, restore)")
	readLinks := flag.String("read-link-roots", "/workspace/managed", "comma-separated directories that a top-level session link may point into for ReadFile, ListFiles and ZipFiles")
	flag.Int64Var(&fc.MaxFileBytes, "max-file-bytes", files.GiB, "largest ReadFile, WriteFile or UploadFile")
	flag.Int64Var(&fc.MaxZipBytes, "max-zip-bytes", files.GiB, "largest total file size of one ZipFiles")
	captureDirs := flag.String("capture-dirs", strings.Join(files.DefaultCaptureRoots, ","), "comma-separated session directories that CaptureSession saves")
	captureExclude := flag.String("capture-exclude", strings.Join(files.DefaultCaptureExclude, ","), "comma-separated names that CaptureSession leaves out at any depth")
	flag.Int64Var(&fc.Limits.StoredBytes, "capture-max-stored-bytes", files.DefaultLimits.StoredBytes, "largest session archive (zstd bytes)")
	flag.Int64Var(&fc.Limits.ExpandedBytes, "capture-max-expanded-bytes", files.DefaultLimits.ExpandedBytes, "largest total file size of a session archive")
	flag.Int64Var(&fc.Limits.Entries, "capture-max-entries", files.DefaultLimits.Entries, "most files and directories in a session archive")
	dialConns := flag.Int("dial-max-conns", guestd.DefaultForwardConns, "most live connections per forwarded dial port; more are reset at once")
	zlevel := flag.String("capture-zstd-level", "fastest", "zstd level of CaptureSession: fastest, default, better or best")
	flag.Parse()
	var ok bool
	if ok, fc.ZstdLevel = zstd.EncoderLevelFromString(*zlevel); !ok {
		fmt.Fprintf(os.Stderr, "bad --capture-zstd-level %q\n", *zlevel)
		os.Exit(2)
	}
	fc.ReadLinkRoots = splitList(*readLinks)
	fc.CaptureRoots = splitList(*captureDirs)
	fc.CaptureExclude = splitList(*captureExclude)

	var lvl slog.Level
	if err := lvl.UnmarshalText([]byte(*logLevel)); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	log := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: lvl}))
	sys := guestd.System{SetClock: sysops.SetClock, GrowFS: sysops.GrowFS}
	sys.AddEntropy = func(b []byte) (bool, error) {
		credited, why, err := sysops.AddEntropy(b)
		if why != nil {
			log.Warn("entropy mixed in, not credited", "err", why)
		}
		return credited, err
	}
	if path := *attachCmd; path != "" {
		sys.Attach = func() error { return sysops.RunAttach(path, 2*time.Minute) }
	}
	if *caBundle != "" {
		paths := sysops.CAPaths{Anchor: *caAnchor, Bundle: *caBundle, NSSDB: *caNSSDB, Certutil: *certutil,
			Nickname: sysops.DefaultCAPaths.Nickname, Log: log}
		sys.InstallCA = func(pem []byte) error { return sysops.InstallEgressCA(paths, pem) }
	}
	if pf := *relayPIDFile; pf != "" {
		sys.ResetRelay = func() (bool, error) { return sysops.SignalPIDFile(pf) }
	}
	if *reportOrder >= 0 {
		// Without the balloon (older templates) or page reporting in the
		// kernel there is no knob; the VM then never returns free memory.
		if err := sysops.SetPageReportingOrder(*reportOrder); err != nil {
			log.Warn("set the page reporting order", "order", *reportOrder, "err", err)
		} else {
			log.Info("page reporting order set", "order", *reportOrder)
		}
	}
	var reclaimer *guestd.Reclaimer
	if *reclaimIdle > 0 {
		if *reclaimIdle < time.Minute {
			fmt.Fprintln(os.Stderr, "--reclaim-idle must be 0 or at least 1m")
			os.Exit(2)
		}
		reclaimer = &guestd.Reclaimer{Idle: *reclaimIdle, Reclaim: sysops.ReclaimMemory, Log: log}
	}
	var managed *guestd.ManagedConfig
	if *managedMnt != "" {
		managed = &guestd.ManagedConfig{
			MountPoint: *managedMnt, Ops: sysops.Managed{},
			Devices: map[pb.ManagedSlot]string{pb.ManagedSlot_MANAGED_SLOT_A: *managedA, pb.ManagedSlot_MANAGED_SLOT_B: *managedB},
		}
	}
	if *dialConns <= 0 {
		fmt.Fprintln(os.Stderr, "--dial-max-conns must be at least 1")
		os.Exit(2)
	}
	// The SetKey dial ports are vsock listeners, so the unix test mode has none.
	var fwd *guestd.Forwards
	if *listen == "" {
		fwd = &guestd.Forwards{Listen: vsock.Listen, Reserved: uint32(*port), MaxConns: *dialConns, Log: log}
	}
	fstore, err := files.New(fc)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if err := run(log, sys, managed, reclaimer, fstore, fwd, *port, *listen, *cgroupRoot, *stateFile, *growMounts, execs.Config{
		DefaultDeadline: *defDeadline, MaxDeadline: *maxDeadline, OutputBytes: *outBytes, OutputBudget: *outBudget, MaxRunning: *maxRunning, Log: log,
	}); err != nil {
		log.Error("guest-daemon failed", "err", err)
		os.Exit(1)
	}
}

// splitList splits a comma-separated flag. An empty flag is an empty list.
func splitList(s string) []string {
	out := []string{}
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func run(log *slog.Logger, sys guestd.System, managed *guestd.ManagedConfig, reclaimer *guestd.Reclaimer, fstore *files.Store, fwd *guestd.Forwards, port uint, listen, cgroupRoot, stateFile, growMounts string, ecfg execs.Config) error {
	if cgroupRoot != "" {
		if err := sysops.EnsureCgroup2(filepath.Dir(cgroupRoot)); err != nil {
			return fmt.Errorf("mount cgroup2: %w", err)
		}
		cg, err := execs.NewCgroups(cgroupRoot)
		if err != nil {
			return err
		}
		ecfg.Isolator = cg
	} else {
		log.Warn("no cgroup root: commands that call setsid escape Cancel and deadlines")
		ecfg.Isolator = execs.ProcessGroups{}
	}
	m, err := execs.NewManager(ecfg)
	if err != nil {
		return err
	}

	var mounts []string
	for _, mp := range strings.Split(growMounts, ",") {
		if mp = strings.TrimSpace(mp); mp != "" {
			mounts = append(mounts, mp)
		}
	}
	// Commands get the daemon's env (the image's guest.env: proxy and CA
	// settings) over the defaults.
	base := maps.Clone(guestd.DefaultBaseEnv)
	for _, kv := range os.Environ() {
		if k, v, ok := strings.Cut(kv, "="); ok && k != "" {
			base[k] = v
		}
	}
	srv, err := guestd.NewServer(guestd.Config{
		Version: version, GrowMounts: mounts, StateFile: stateFile, BaseEnv: base, Managed: managed,
		Reclaimer: reclaimer, Files: fstore, Forwards: fwd, Log: log,
	}, sys, m)
	if err != nil {
		return err
	}

	// No TCP listener: the API is plaintext with a bearer key, so it is only
	// served on vsock (reached through the node agent) or, for tests, on a
	// Unix socket only root can open.
	var ln net.Listener
	switch path, isUnix := strings.CutPrefix(listen, "unix:"); {
	case isUnix && path != "":
		_ = os.Remove(path)
		ln, err = net.Listen("unix", path)
		if err == nil {
			err = os.Chmod(path, 0o600)
		}
	case listen != "":
		return fmt.Errorf("--listen must be unix:<path>, got %q", listen)
	default:
		ln, err = vsock.Listen(uint32(port))
	}
	if err != nil {
		return err
	}
	// Large static flow-control windows: vsock has almost no latency, and
	// session restores and file writes stream hundreds of MiB to the guest.
	gs := srv.NewGRPCServer(grpc.InitialWindowSize(windowBytes), grpc.InitialConnWindowSize(windowBytes),
		grpc.ReadBufferSize(1<<20), grpc.WriteBufferSize(1<<20))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go reclaimer.Run(ctx)
	go func() {
		<-ctx.Done()
		log.Info("stopping")
		gs.Stop()
	}()
	log.Info("guest-daemon serving", "version", version, "addr", ln.Addr().String())
	err = gs.Serve(ln)
	m.Shutdown()
	if ctx.Err() != nil {
		return nil
	}
	return err
}
