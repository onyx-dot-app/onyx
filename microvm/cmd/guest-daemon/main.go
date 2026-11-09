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
	"slices"
	"strings"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/sysops"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/vsock"
)

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
	var bf browserFlags
	flag.StringVar(&bf.chrome, "browser-bin", "/opt/chrome/chrome,/usr/bin/chromium", "comma-separated Chromium binaries, first found wins (Chrome for Testing, then Debian); empty disables the browser calls")
	flag.StringVar(&bf.xvfb, "browser-xvfb", "/usr/bin/Xvfb", "Xvfb binary")
	flag.StringVar(&bf.user, "browser-user", "sandbox", "non-root user that runs Xvfb and Chromium (Chromium's sandbox needs it)")
	flag.StringVar(&bf.profile, "browser-profile-dir", "/workspace/.craft/browser-profile", "saved browser profile (one per VM)")
	flag.StringVar(&bf.work, "browser-work-dir", "/var/lib/craft-browser", "dir of the live browser profile")
	flag.StringVar(&bf.cgroup, "browser-cgroup", "/sys/fs/cgroup/guestd-browser", "cgroup v2 dir of the browser; empty uses process groups and no memory limit")
	flag.Int64Var(&bf.memMax, "browser-memory-max", 2<<30, "memory limit of the browser cgroup (Chromium and Xvfb), bytes")
	flag.IntVar(&bf.cdpPort, "browser-cdp-port", 9222, "Chromium DevTools TCP port on 127.0.0.1")
	flag.UintVar(&bf.vsockPort, "browser-vsock-port", 9222, "guest vsock port that forwards to the DevTools port (node agent Dial)")
	flag.StringVar(&bf.screen, "browser-screen", "1280x800x24", "Xvfb screen, WxHxDepth")
	flag.Parse()

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
	if pf := *relayPIDFile; pf != "" {
		sys.ResetRelay = func() (bool, error) { return sysops.SignalPIDFile(pf) }
	}
	if err := run(log, sys, *port, *listen, *cgroupRoot, *stateFile, *growMounts, bf, execs.Config{
		DefaultDeadline: *defDeadline, MaxDeadline: *maxDeadline, OutputBytes: *outBytes, OutputBudget: *outBudget, MaxRunning: *maxRunning, Log: log,
	}); err != nil {
		log.Error("guest-daemon failed", "err", err)
		os.Exit(1)
	}
}

type browserFlags struct {
	chrome, xvfb, user, profile, work, cgroup, screen string
	memMax                                            int64
	cdpPort                                           int
	vsockPort                                         uint
}

// newBrowser returns the browser manager. Its cgroup is separate from the
// executions' (Cancel, List and the output budget do not apply to it).
func newBrowser(log *slog.Logger, bf browserFlags, daemonPort uint, listen string, useCgroups bool, env map[string]string) (*browser.Manager, error) {
	var bins []string
	for _, b := range strings.Split(bf.chrome, ",") {
		if b = strings.TrimSpace(b); b != "" {
			bins = append(bins, b)
		}
	}
	if len(bins) == 0 {
		return browser.New(browser.Config{Log: log})
	}
	if bf.vsockPort == 0 || bf.vsockPort == daemonPort || bf.vsockPort > 1<<32-1 {
		return nil, fmt.Errorf("--browser-vsock-port %d must be set and differ from --port", bf.vsockPort)
	}
	cfg := browser.Config{
		ChromeBins: bins, XvfbBin: bf.xvfb, User: bf.user, ProfileDir: bf.profile, WorkDir: bf.work,
		Screen: bf.screen, CDPPort: bf.cdpPort, VsockPort: uint32(bf.vsockPort), MemoryMax: bf.memMax, Log: log,
		Isolator: execs.ProcessGroups{},
	}
	for _, k := range slices.Sorted(maps.Keys(env)) {
		cfg.Env = append(cfg.Env, k+"="+env[k])
	}
	if path, ok := strings.CutPrefix(listen, "unix:"); ok {
		// Tests: the CDP port is a Unix socket next to the daemon's.
		cfg.Listen = func(port uint32) (net.Listener, error) {
			return net.Listen("unix", fmt.Sprintf("%s_%d", path, port))
		}
	} else {
		cfg.Listen = vsock.Listen
	}
	if useCgroups && bf.cgroup != "" {
		cg, err := execs.NewCgroups(bf.cgroup)
		if err != nil {
			return nil, fmt.Errorf("browser cgroup: %w", err)
		}
		cfg.Isolator, cfg.CgroupRoot = cg, bf.cgroup
	}
	return browser.New(cfg)
}

func run(log *slog.Logger, sys guestd.System, port uint, listen, cgroupRoot, stateFile, growMounts string, bf browserFlags, ecfg execs.Config) error {
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
	br, err := newBrowser(log, bf, port, listen, cgroupRoot != "", base)
	if err != nil {
		return err
	}
	srv, err := guestd.NewServer(guestd.Config{Version: version, GrowMounts: mounts, StateFile: stateFile, BaseEnv: base, Browser: br, Log: log}, sys, m)
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
	gs := srv.NewGRPCServer()

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go func() {
		<-ctx.Done()
		log.Info("stopping")
		gs.Stop()
	}()
	log.Info("guest-daemon serving", "version", version, "addr", ln.Addr().String())
	err = gs.Serve(ln)
	// Stop the browser cleanly (it saves the profile), then the commands.
	sctx, scancel := context.WithTimeout(context.Background(), 30*time.Second)
	if r, berr := br.Stop(sctx); berr != nil {
		log.Warn("stop browser", "err", berr)
	} else if r.WasRunning {
		log.Info("browser stopped", "clean", r.Clean, "profile_saved", r.ProfileSaved)
	}
	scancel()
	m.Shutdown()
	if ctx.Err() != nil {
		return nil
	}
	return err
}
