//go:build !linux

package fcvm

import (
	"context"
	"errors"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
)

// Launch is only supported on Linux.
func (l *Launcher) Launch(_ context.Context, _ agent.LaunchSpec) (agent.Process, error) {
	return nil, errors.New("firecracker VMs need Linux")
}
