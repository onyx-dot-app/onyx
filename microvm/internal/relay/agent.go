package relay

import (
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
)

// GuestPort is the vsock port the guest connects to for egress. Firecracker
// maps a guest connect to (CID 2, port P) to the host socket <uds>_P.
const GuestPort = 3128

// AgentEgress implements agent.Egress with a Relay.
type AgentEgress struct {
	Relay *Relay
}

// Attach listens on the VM's <vsock uds>_3128 and relays its connections.
func (a *AgentEgress) Attach(vm agent.VM, info agent.ProcInfo) error {
	sub, err := Subject(vm.TenantID, vm.SandboxID)
	if err != nil {
		return err
	}
	if info.VsockUDS == "" {
		return errors.New("VM has no vsock socket path")
	}
	path := info.VsockUDS + "_" + strconv.Itoa(GuestPort)
	// Close a listener of an earlier VM first: closing it later would
	// remove the new socket file.
	a.Relay.Detach(vm.SandboxID)
	// A previous agent process may have left the socket file.
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	ln, err := net.Listen("unix", path)
	if err != nil {
		return err
	}
	// Firecracker runs as the VM UID and must connect to the socket.
	if err := os.Chown(path, int(vm.UID), int(vm.UID)); err != nil {
		_ = ln.Close()
		return fmt.Errorf("chown %s: %w", path, err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		_ = ln.Close()
		return err
	}
	a.Relay.Start(ln, VM{SandboxID: vm.SandboxID, Subject: sub, Generation: vm.Generation})
	return nil
}

// Detach stops relaying for the VM.
func (a *AgentEgress) Detach(sandboxID string) { a.Relay.Detach(sandboxID) }

// CloseAll closes the VM's relay connections.
func (a *AgentEgress) CloseAll(sandboxID string) int { return a.Relay.CloseAll(sandboxID) }
