//go:build linux

package tplbuild

import (
	"context"
	"errors"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
)

// FirecrackerVMM boots template VMs with the jailer. It implements VMM.
type FirecrackerVMM struct {
	Launcher *fcvm.Launcher
}

// Boot implements VMM.
func (v FirecrackerVMM) Boot(ctx context.Context, id string, uid uint32, files []File, cfg BootConfig) (VM, error) {
	fs := make([]fcvm.FileSource, 0, len(files))
	for _, f := range files {
		fs = append(fs, fcvm.FileSource{Name: f.Name, Src: f.Src})
	}
	p, err := v.Launcher.Boot(ctx, id, uid, fs, fcvm.BootSpec{
		Kernel: cfg.KernelFile, BootArgs: cfg.BootArgs, Drives: cfg.Drives, VCPUs: cfg.VCPUs, MemMiB: cfg.MemMiB,
		Balloon: cfg.Balloon,
	})
	if err != nil {
		if errors.Is(err, agent.ErrVMLeft) {
			return nil, errors.Join(err, ErrVMLeft)
		}
		return nil, err
	}
	return p, nil
}
