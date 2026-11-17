package execs

import (
	"os/exec"
	"syscall"
)

// Isolator puts each execution in its own kill group.
type Isolator interface {
	NewGroup(id string) (Group, error)
}

// Group holds every process of one execution.
type Group interface {
	// Prepare sets up cmd so that its process starts inside the group.
	Prepare(cmd *exec.Cmd)
	// Started records the main process after a successful start.
	Started(pid int)
	// Kill sends SIGKILL to every process in the group.
	Kill() error
	// Signal sends sig to the process group of the main process (the
	// session that it leads). Processes that left it do not get sig.
	Signal(sig syscall.Signal) error
	// Close releases the group after its processes are gone.
	Close() error
}
