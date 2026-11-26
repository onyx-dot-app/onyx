// Command guest-daemon is the Sandboxd gRPC server inside each Craft
// micro-VM. It listens on vsock and runs as root. It runs commands as the
// sandbox user (--command-user), each in its own cgroup. It is not PID 1: the
// VM init starts it and restarts it. With --container it runs in a sandbox
// container instead, on TCP with TLS (README).
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"maps"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/klauspost/compress/zstd"
	"google.golang.org/grpc"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/sysops"
)

// windowBytes is the HTTP/2 flow-control window of the gRPC server.
const windowBytes = 16 << 20

// version is set with -ldflags "-X main.version=...".
var version = "dev"

func main() {
	port := flag.Uint("port", 52, "vsock port")
	listen := flag.String("listen", "", "listen on unix:<path> (tests) or tcp:<host:port> (needs --tls-cert, --tls-key and --key-file) instead of vsock")
	tlsCert := flag.String("tls-cert", "", "TLS certificate (PEM) of a tcp: listener")
	tlsKey := flag.String("tls-key", "", "TLS private key (PEM) of a tcp: listener")
	keyFile := flag.String("key-file", "", "file with the daemon key, set at start; SetKey with another key then fails")
	container := flag.Bool("container", false, "run in a sandbox container: Init skips the clock and entropy, and the VM-only flags default to off")
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
	flag.StringVar(&fc.OnyxRoot, "onyx-root", files.DefaultOnyxRoot, "directory of the files Onyx writes outside every session; file calls with no session ID never follow a link out of it")
	flag.StringVar(&fc.SkillsRoot, "skills-root", files.DefaultSkillsRoot, "root-owned folder where InstallSkill puts each skill")
	readLinks := flag.String("read-link-roots", files.DefaultSkillsRoot+",/mnt/user-uploads,/mnt/spaces", "comma-separated directories that a top-level session link may point into for ReadFile, ListFiles and ZipFiles")
	flag.Int64Var(&fc.MaxFileBytes, "max-file-bytes", files.GiB, "largest ReadFile, WriteFile or UploadFile")
	flag.Int64Var(&fc.MaxZipBytes, "max-zip-bytes", files.GiB, "largest total file size of one ZipFiles")
	captureDirs := flag.String("capture-dirs", strings.Join(files.DefaultCaptureRoots, ","), "comma-separated session directories that CaptureSession saves")
	captureExclude := flag.String("capture-exclude", strings.Join(files.DefaultCaptureExclude, ","), "comma-separated names that CaptureSession leaves out at any depth")
	flag.Int64Var(&fc.Limits.StoredBytes, "capture-max-stored-bytes", files.DefaultLimits.StoredBytes, "largest session archive (zstd bytes)")
	flag.Int64Var(&fc.Limits.ExpandedBytes, "capture-max-expanded-bytes", files.DefaultLimits.ExpandedBytes, "largest total file size of a session archive")
	flag.Int64Var(&fc.Limits.Entries, "capture-max-entries", files.DefaultLimits.Entries, "most files and directories in a session archive")
	zlevel := flag.String("capture-zstd-level", "fastest", "zstd level of CaptureSession: fastest, default, better or best")
	fileOwner := flag.String("file-owner", files.DefaultOwner, "uid:gid that gets the files and directories that WriteFile, UploadFile and RestoreSession make in the sessions root and the onyx root (the image's sandbox user); empty: they stay root's")
	browserBin := flag.String("browser-binary", browser.DefaultBinary, "Chrome that BrowserStart runs; empty turns the browser calls off")
	cmdUser := flag.String("command-user", files.DefaultOwner, "uid:gid that runs every command (the image's sandbox user); empty: commands run as root")
	flag.Parse()
	if *container {
		if err := applyContainerDefaults(flag.CommandLine); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
	}
	key, err := readKeyFile(*keyFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "bad --key-file: %v\n", err)
		os.Exit(2)
	}
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
	sys := guestd.System{GrowFS: sysops.GrowFS}
	if !*container {
		sys.SetClock = sysops.SetClock
		sys.AddEntropy = func(b []byte) (bool, error) {
			credited, why, err := sysops.AddEntropy(b)
			if why != nil {
				log.Warn("entropy mixed in, not credited", "err", why)
			}
			return credited, err
		}
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
	var bcfg *browser.Config
	if *browserBin != "" {
		bcfg = &browser.Config{Binary: *browserBin, ProfileDir: browserProfileDir(ident), Log: log}
		if ident != nil {
			bcfg.Credential = ident.cred
		}
	}
	lc := listenConfig{Spec: *listen, Port: *port, TLSCert: *tlsCert, TLSKey: *tlsKey, KeyFile: *keyFile}
	if err := run(log, sys, managed, reclaimer, fstore, ident, bcfg, lc, key, *cgroupRoot, *stateFile, *growMounts, execs.Config{
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

// browserProfileDir is the browser's --user-data-dir, in the HOME of the
// command user (else the daemon's).
func browserProfileDir(ident *commandIdentity) string {
	home := ""
	if ident != nil {
		home = ident.env["HOME"]
	}
	if home == "" {
		home = os.Getenv("HOME")
	}
	if home == "" {
		home = "/root"
	}
	return filepath.Join(home, ".config", "onyx-browser")
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

func run(log *slog.Logger, sys guestd.System, managed *guestd.ManagedConfig, reclaimer *guestd.Reclaimer, fstore *files.Store, ident *commandIdentity, bcfg *browser.Config, lc listenConfig, key, cgroupRoot, stateFile, growMounts string, ecfg execs.Config) error {
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
	var br *browser.Browser
	if bcfg != nil {
		bcfg.Isolator = execs.ProcessGroups{}
		if cgroupRoot != "" {
			// A sibling of the executions' root: the execution manager never
			// sees the browser, and a daemon restart kills a leftover one.
			cg, err := execs.NewCgroups(filepath.Join(filepath.Dir(cgroupRoot), "guestd-browser"))
			if err != nil {
				return err
			}
			bcfg.Isolator = cg
		}
		br = browser.New(*bcfg)
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
		Version: version, GrowMounts: mounts, StateFile: stateFile, BaseEnv: base, Managed: managed, Browser: br,
		Reclaimer: reclaimer, Files: fstore, Key: key, Log: log,
	}, sys, m)
	if err != nil {
		return err
	}

	// vsock (through the node agent), a Unix socket only the daemon user can
	// open (tests), or TCP with TLS and a key file (containers).
	ln, transport, err := listen(lc)
	if err != nil {
		return err
	}
	// Large static flow-control windows: vsock has almost no latency, and
	// session restores and file writes stream hundreds of MiB to the guest.
	gs := srv.NewGRPCServer(append(transport, grpc.InitialWindowSize(windowBytes), grpc.InitialConnWindowSize(windowBytes),
		grpc.ReadBufferSize(1<<20), grpc.WriteBufferSize(1<<20))...)

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
	if br != nil {
		if _, serr := br.Stop(); serr != nil {
			log.Warn("stop browser", "err", serr)
		}
	}
	if ctx.Err() != nil {
		return nil
	}
	return err
}
