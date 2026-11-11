//go:build unix

package execs

import (
	"errors"
	"os/exec"
	"syscall"
)

// ProcessGroups isolates each execution in its own session and process
// group. A process that calls setsid escapes it; use Cgroups in the VM.
type ProcessGroups struct{}

// NewGroup implements Isolator.
func (ProcessGroups) NewGroup(string) (Group, error) { return &pgroup{}, nil }

type pgroup struct{ pid int }

func (g *pgroup) Prepare(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

func (g *pgroup) Started(pid int) { g.pid = pid }

func (g *pgroup) Kill() error {
	if g.pid <= 0 {
		return nil
	}
	err := syscall.Kill(-g.pid, syscall.SIGKILL)
	if errors.Is(err, syscall.ESRCH) {
		return nil
	}
	return err
}

func (g *pgroup) Signal(sig syscall.Signal) error { return signalGroup(g.pid, sig) }

func (g *pgroup) Close() error { return nil }

// signalGroup sends sig to process group pgid. A group that is gone is not
// an error.
func signalGroup(pgid int, sig syscall.Signal) error {
	if pgid <= 0 {
		return nil
	}
	err := syscall.Kill(-pgid, sig)
	if errors.Is(err, syscall.ESRCH) {
		return nil
	}
	return err
}
