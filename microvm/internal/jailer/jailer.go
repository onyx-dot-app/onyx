// Package jailer builds the command that starts one Firecracker VM under the
// jailer, in its own systemd scope in a host slice.
//
// The command is
//
//	nsenter -t 1 -m -- systemd-run --scope --slice=<slice> --unit=fcvm-<id> -- jailer ...
//
// nsenter enters the host mount namespace, so systemd-run reaches the host
// systemd and the scope (the VM cgroup) is outside the agent's container
// cgroup. VMs then survive an agent restart. nsenter, systemd-run and the
// jailer all exec in place. The jailer starts Firecracker in a new PID
// namespace and writes its host PID to <root>/firecracker.pid.
//
// Because the jailer runs in the host mount namespace, every path in the
// command must be a host path. The agent's data dir must be mounted at the
// same path in the container and on the host.
package jailer

import (
	"fmt"
	"path/filepath"
	"regexp"
	"strconv"
)

// ExecName is the file name of the Firecracker binary. The jailer uses it in
// the chroot path and Firecracker shows it as its comm.
const ExecName = "firecracker"

// In-chroot paths.
const (
	APISock = "/api.sock"
	LogFile = "/fc.log"
	PIDFile = "/" + ExecName + ".pid"
)

// MaxSockPath is the longest host path the agent accepts for a VM socket.
// sun_path holds 108 bytes, including the final NUL.
const MaxSockPath = 107

var idRE = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,63}$`)

// ValidID reports whether id is a valid jailer --id.
func ValidID(id string) bool { return idRE.MatchString(id) }

// Layout is the jailer chroot layout under the data dir.
type Layout struct {
	// ChrootBase is the jailer --chroot-base-dir.
	ChrootBase string
}

// ChrootDir is <base>/firecracker/<id>. The agent keeps files that the VM
// must not see here, outside the root.
func (l Layout) ChrootDir(id string) string { return filepath.Join(l.ChrootBase, ExecName, id) }

// RootDir is the directory that the jailer chroots into.
func (l Layout) RootDir(id string) string { return filepath.Join(l.ChrootDir(id), "root") }

// HostPath maps an in-chroot path to its host path.
func (l Layout) HostPath(id, inChroot string) string {
	return filepath.Join(l.RootDir(id), inChroot)
}

// ConsoleLog is the host path of the VM serial console log.
func (l Layout) ConsoleLog(id string) string { return filepath.Join(l.ChrootDir(id), "console.log") }

// ScopeUnit is the systemd scope of a VM.
func ScopeUnit(id string) string { return "fcvm-" + id + ".scope" }

// Command builds the launch command line.
type Command struct {
	JailerBin      string
	FirecrackerBin string
	Layout         Layout
	// Slice is the host systemd slice, for example "fcvms.slice".
	Slice string
	// HostMountNS wraps the command in nsenter -t 1 -m.
	HostMountNS bool
	// LogLevel is the Firecracker log level.
	LogLevel string
}

// DefaultMemOverheadMiB is the memory a VM scope gets on top of the guest
// memory: Firecracker itself (its heap, vCPU and device threads) and the
// page cache of the VM's drives (results/mem-admission.md).
const DefaultMemOverheadMiB = 128

// Limits are the cgroup limits of a VM scope. Zero means no limit.
type Limits struct {
	// MemoryMaxBytes is memory.max (systemd MemoryMax). The guest cannot
	// use more than its memory, so only a broken or hostile Firecracker
	// process hits it; the kernel then kills that VM only.
	MemoryMaxBytes uint64
	// CPUQuotaPercent is cpu.max as a percent of one CPU (systemd
	// CPUQuota): 100 per vCPU.
	CPUQuotaPercent uint32
}

// VMLimits returns the limits of a VM with vcpus and memMiB of guest
// memory: memory.max = guest memory + overheadMiB, cpu.max = vcpus CPUs.
func VMLimits(vcpus, memMiB, overheadMiB uint32) Limits {
	return Limits{MemoryMaxBytes: (uint64(memMiB) + uint64(overheadMiB)) << 20, CPUQuotaPercent: vcpus * 100}
}

// Argv returns the command line for VM id with jailer UID and GID uid. The
// VM's scope gets the limits lim.
func (c Command) Argv(id string, uid uint32, lim Limits) ([]string, error) {
	if !ValidID(id) {
		return nil, fmt.Errorf("invalid VM id %q", id)
	}
	u := strconv.FormatUint(uint64(uid), 10)
	level := c.LogLevel
	if level == "" {
		level = "Warning"
	}
	jail := []string{
		c.JailerBin,
		"--id", id,
		"--exec-file", c.FirecrackerBin,
		"--uid", u,
		"--gid", u,
		"--chroot-base-dir", c.Layout.ChrootBase,
		"--cgroup-version", "2",
		"--new-pid-ns",
		"--",
		"--api-sock", APISock,
		"--level", level,
		"--log-path", LogFile,
	}
	argv := []string{
		"systemd-run", "--quiet", "--scope", "--collect",
		"--slice=" + c.Slice,
		"--unit=" + ScopeUnit(id),
	}
	if lim.MemoryMaxBytes > 0 {
		argv = append(argv, "--property=MemoryMax="+strconv.FormatUint(lim.MemoryMaxBytes, 10))
	}
	if lim.CPUQuotaPercent > 0 {
		argv = append(argv, "--property=CPUQuota="+strconv.FormatUint(uint64(lim.CPUQuotaPercent), 10)+"%")
	}
	argv = append(append(argv, "--"), jail...)
	if c.HostMountNS {
		argv = append([]string{"nsenter", "-t", "1", "-m", "--"}, argv...)
	}
	return argv, nil
}

// SystemctlArgv returns a systemctl command line that runs in the same mount
// namespace as the launch command.
func (c Command) SystemctlArgv(args ...string) []string {
	argv := append([]string{"systemctl"}, args...)
	if c.HostMountNS {
		argv = append([]string{"nsenter", "-t", "1", "-m", "--"}, argv...)
	}
	return argv
}
