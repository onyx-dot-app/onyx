// Command guest-daemon is the Sandboxd gRPC server inside each Craft
// micro-VM. It listens on vsock and runs as root. It runs commands as the
// sandbox user (--command-user), each in its own cgroup. It is not PID 1: the
// VM init starts it and restarts it.
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
	maxRunning := flag.Int("max-running", 64, "most running executions (at most --max-tracked)")
	maxTracked := flag.Int("max-tracked", 64, "most execution records, running and ended; a new one drops the least recently used ended record")
	logLevel := flag.String("log-level", "info", "debug, info, warn or error")
	managedMounts := flag.String("managed-mounts", guestd.FormatManagedMounts(guestd.DefaultManagedMounts),
		"comma-separated name=/mount/point:/dev/slotA:/dev/slotB managed mounts (the image's attach script); empty turns MountManaged off")
	reportOrder := flag.Int("page-reporting-order", 0, "balloon free page reporting order to set at start (0 reports every free page); -1 leaves the kernel default")
	reclaimIdle := flag.Duration("reclaim-idle", 5*time.Minute, "drop the page cache after this long without daemon calls (Health does not count); 0 turns it off")
	caAnchor := flag.String("ca-anchor", sysops.DefaultCAPaths.Anchor, "egress CA file that update-ca-certificates reads")
	caBundle := flag.String("ca-bundle", sysops.DefaultCAPaths.Bundle, "system CA bundle that Init adds the SetKey egress CA to; empty turns the CA install off")
	caNSSDB := flag.String("ca-nssdb", sysops.DefaultCAPaths.NSSDB, "NSS database (Chromium) that gets the egress CA; certutil runs as its owner; empty to skip")
	certutil := flag.String("certutil", sysops.DefaultCAPaths.Certutil, "NSS certutil program")
	var fc files.Config
	flag.StringVar(&fc.SessionsRoot, "sessions-root", files.DefaultSessionsRoot, "directory with one directory per session (file calls, capture, restore)")
	readLinks := flag.String("read-link-roots", "/mnt/skills,/mnt/user-uploads,/mnt/spaces", "comma-separated directories that a top-level session link may point into for ReadFile, ListFiles and ZipFiles")
	flag.Int64Var(&fc.MaxFileBytes, "max-file-bytes", files.GiB, "largest ReadFile, WriteFile or UploadFile")
	flag.Int64Var(&fc.MaxZipBytes, "max-zip-bytes", files.GiB, "largest total file size of one ZipFiles")
	captureDirs := flag.String("capture-dirs", strings.Join(files.DefaultCaptureRoots, ","), "comma-separated session directories that CaptureSession saves")
	captureExclude := flag.String("capture-exclude", strings.Join(files.DefaultCaptureExclude, ","), "comma-separated names that CaptureSession leaves out at any depth")
	flag.Int64Var(&fc.Limits.StoredBytes, "capture-max-stored-bytes", files.DefaultLimits.StoredBytes, "largest session archive (zstd bytes)")
	flag.Int64Var(&fc.Limits.ExpandedBytes, "capture-max-expanded-bytes", files.DefaultLimits.ExpandedBytes, "largest total file size of a session archive")
	flag.Int64Var(&fc.Limits.Entries, "capture-max-entries", files.DefaultLimits.Entries, "most files and directories in a session archive")
	zlevel := flag.String("capture-zstd-level", "fastest", "zstd level of CaptureSession: fastest, default, better or best")
	fileOwner := flag.String("file-owner", files.DefaultOwner, "uid:gid that gets the files and directories that WriteFile, UploadFile and RestoreSession make in the sessions root (the image's sandbox user); empty: they stay root's")
	cmdUser := flag.String("command-user", files.DefaultOwner, "uid:gid that runs every command (the image's sandbox user); empty: commands run as root")
	flag.Parse()
	var ok bool
	if ok, fc.ZstdLevel = zstd.EncoderLevelFromString(*zlevel); !ok {
		fmt.Fprintf(os.Stderr, "bad --capture-zstd-level %q\n", *zlevel)
		os.Exit(2)
	}
	owner, err := files.ParseOwner(*fileOwner)
	if err != nil {
		fmt.Fprintf(os.Stderr, "bad --file-owner: %v\n", err)
		os.Exit(2)
	}
	fc.Owner = owner
	ident, err := parseCommandUser(*cmdUser, lookupAccount)
	if err != nil {
		fmt.Fprintf(os.Stderr, "bad --command-user: %v\n", err)
		os.Exit(2)
	}
	if ident != nil && os.Geteuid() != 0 {
		fmt.Fprintf(os.Stderr, "--command-user=%s needs a root daemon; run as root or set --command-user=\n", *cmdUser)
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
	mounts, err := guestd.ParseManagedMounts(*managedMounts)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	var managed *guestd.ManagedConfig
	if len(mounts) > 0 {
		managed = &guestd.ManagedConfig{Mounts: mounts, Ops: sysops.Managed{}}
	}
	fstore, err := files.New(fc)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if err := run(log, sys, managed, reclaimer, fstore, ident, *port, *listen, *cgroupRoot, *stateFile, *growMounts, execs.Config{
		DefaultDeadline: *defDeadline, MaxDeadline: *maxDeadline, OutputBytes: *outBytes, OutputBudget: *outBudget, MaxRunning: *maxRunning, MaxTracked: *maxTracked, Log: log,
	}); err != nil {
		log.Error("guest-daemon failed", "err", err)
		os.Exit(1)
	}
}

// baseEnv is the command env before Init: the defaults, the daemon's env
// over them, then the command user's HOME, USER and LOGNAME.
func baseEnv(environ []string, ident *commandIdentity) map[string]string {
	base := maps.Clone(guestd.DefaultBaseEnv)
	for _, kv := range environ {
		if k, v, ok := strings.Cut(kv, "="); ok && k != "" {
			base[k] = v
		}
	}
	if ident != nil {
		maps.Copy(base, ident.env)
	}
	return base
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

func run(log *slog.Logger, sys guestd.System, managed *guestd.ManagedConfig, reclaimer *guestd.Reclaimer, fstore *files.Store, ident *commandIdentity, port uint, listen, cgroupRoot, stateFile, growMounts string, ecfg execs.Config) error {
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
	if ident != nil {
		ecfg.Credential = ident.cred
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
	// The image's guest.env (proxy and CA settings) comes in as the daemon's env.
	base := baseEnv(os.Environ(), ident)
	srv, err := guestd.NewServer(guestd.Config{
		Version: version, GrowMounts: mounts, StateFile: stateFile, BaseEnv: base, Managed: managed,
		Reclaimer: reclaimer, Files: fstore, Log: log,
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
