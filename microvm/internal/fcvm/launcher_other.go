//go:build !linux

package fcvm

import (
	"context"
	"errors"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
)

var errLinux = errors.New("firecracker VMs need Linux")

// Launch is only supported on Linux.
func (l *Launcher) Launch(context.Context, agent.LaunchSpec) (agent.Process, error) {
	return nil, errLinux
}

// Adopt is only supported on Linux.
func (l *Launcher) Adopt(context.Context, journal.Record) (agent.Process, error) {
	return nil, errLinux
}

// Scan is only supported on Linux.
func (l *Launcher) Scan() ([]agent.Candidate, error) { return nil, errLinux }

// Remove is only supported on Linux.
func (l *Launcher) Remove(context.Context, agent.Candidate) error { return errLinux }
