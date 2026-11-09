// Command host-agent runs the Firecracker VMs of one Craft node.
//
// It serves the HostAgent gRPC API on a Unix socket. VMs run in a host
// systemd slice and keep running when the agent stops.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/binaries"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/server"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
)

// version is set with -ldflags "-X main.version=...".
var version = "dev"

// The longest in-chroot socket name the agent uses (the egress relay socket).
const longestSock = "/v.sock_65535"

type flags struct {
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
}

func main() {
	var f flags
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
	uids, err := jailer.NewUIDPool(uint32(f.uidBase), uint32(f.uidCount))
	if err != nil {
		return err
	}
	launcher := &fcvm.Launcher{Cmd: cmd, Log: log}
	m := agent.NewManager(agent.Config{
		MinFreeMemMiB:    f.minFreeMemMiB,
		MinFreeDiskBytes: f.minFreeDiskGB * uint64(scratch.GiB),
		MaxScratchGiB:    uint32(f.maxScratchGiB),
		StartTimeout:     f.startTimeout,
		StopTimeout:      f.stopTimeout,
		TombstoneTTL:     24 * time.Hour,
	},
		&template.Store{Dir: filepath.Join(f.dataDir, "templates")},
		launcher,
		hostinfo.Stats{DataDir: f.dataDir},
		uids,
		agent.Versions{Firecracker: bins.Version, HostKernel: hostinfo.KernelRelease(), CPUModel: hostinfo.CPUModel(), Agent: version},
		log,
	)
	m.UseJournal(&journal.Journal{Dir: filepath.Join(f.dataDir, "journal")})
	t0 := time.Now()
	rep, err := m.Recover(context.Background(), launcher)
	if err != nil {
		return err
	}
	log.Info("recovered VMs", "adopted", rep.Adopted, "unresponsive", rep.Unresponsive, "exited", rep.Exited,
		"abandoned", rep.Abandoned, "unverified", rep.Unverified, "unreadable", rep.Unreadable,
		"tombstones", rep.Tombstones, "orphans_killed", rep.Orphans, "leftovers_removed", rep.Leftovers,
		"ms", time.Since(t0).Milliseconds())
	ln, err := server.ListenUnix(f.socket)
	if err != nil {
		return err
	}
	srv := server.New(m)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		// VMs keep running: they are in the host slice, not in this process.
		srv.GracefulStop()
	}()
	log.Info("host agent ready", "socket", f.socket, "firecracker", bins.Version, "version", version)
	return srv.Serve(ln)
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
	for _, d := range []string{"templates", "jail", "bin", "run", "journal"} {
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
	if f.maxScratchGiB > math.MaxUint32 {
		return fmt.Errorf("--max-scratch-gib %d is too large", f.maxScratchGiB)
	}
	return nil
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
