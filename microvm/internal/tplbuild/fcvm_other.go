//go:build !linux

package tplbuild

import (
	"context"
	"errors"

	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
)

// FirecrackerVMM boots template VMs with the jailer. It needs Linux.
type FirecrackerVMM struct {
	Launcher *fcvm.Launcher
}

// Boot is only supported on Linux.
func (FirecrackerVMM) Boot(context.Context, string, uint32, []File, BootConfig) (VM, error) {
	return nil, errors.New("template builds need Linux")
}
