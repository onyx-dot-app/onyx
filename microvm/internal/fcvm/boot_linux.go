//go:build linux

package fcvm

import (
	"context"
	"fmt"

	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/client/operations"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/models"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
)

// BootSpec is a cold boot of a template VM.
type BootSpec struct {
	// Kernel is the kernel file name in the chroot.
	Kernel   string
	BootArgs string
	Drives   []template.Drive
	VCPUs    uint32
	MemMiB   uint32
}

// Boot starts VM id from files (each a reflink copy; the writable drives
// owned by the VM UID) and boots it: kernel, drives in order, machine
// config, vsock (CID 3, /v.sock), InstanceStart.
func (l *Launcher) Boot(ctx context.Context, id string, uid uint32, files []FileSource, s BootSpec) (*Proc, error) {
	writable := map[string]bool{}
	for _, d := range s.Drives {
		if !d.ReadOnly {
			writable[d.File] = true
		}
	}
	for i := range files {
		files[i].VMOwned = writable[files[i].Name]
	}
	p, err := l.Spawn(ctx, id, uid, files)
	if err != nil {
		return nil, err
	}
	if err := p.boot(ctx, s); err != nil {
		return nil, l.abort(p, fmt.Errorf("%w; console: %s", err, tail(l.Cmd.Layout.ConsoleLog(id))), nil)
	}
	return p, nil
}

func (p *Proc) boot(ctx context.Context, s BootSpec) error {
	api := p.API()
	kernel := "/" + s.Kernel
	if _, err := api.PutGuestBootSourceContext(ctx, &operations.PutGuestBootSourceParams{
		Body: &models.BootSource{KernelImagePath: &kernel, BootArgs: s.BootArgs},
	}); err != nil {
		return apiErr("boot source", err)
	}
	for i, d := range s.Drives {
		driveID, root, path := d.ID, i == 0, "/"+d.File
		if _, err := api.PutGuestDriveByIDContext(ctx, &operations.PutGuestDriveByIDParams{
			DriveID: driveID, Body: &models.Drive{DriveID: &driveID, IsRootDevice: &root, IsReadOnly: d.ReadOnly, PathOnHost: path},
		}); err != nil {
			return apiErr("drive "+driveID, err)
		}
	}
	vcpus, mem := int64(s.VCPUs), int64(s.MemMiB)
	if _, err := api.PutMachineConfigurationContext(ctx, &operations.PutMachineConfigurationParams{
		Body: &models.MachineConfiguration{VcpuCount: &vcpus, MemSizeMib: &mem},
	}); err != nil {
		return apiErr("machine config", err)
	}
	cid, uds := int64(template.GuestCID), template.VsockUDS
	if _, err := api.PutGuestVsockContext(ctx, &operations.PutGuestVsockParams{Body: &models.Vsock{GuestCid: &cid, UdsPath: &uds}}); err != nil {
		return apiErr("vsock", err)
	}
	start := models.InstanceActionInfoActionTypeInstanceStart
	_, err := api.CreateSyncActionContext(ctx, &operations.CreateSyncActionParams{Info: &models.InstanceActionInfo{ActionType: &start}})
	return apiErr("start", err)
}

// VsockPath is the host path of the VM's vsock UDS.
func (p *Proc) VsockPath() string { return p.l.Cmd.Layout.HostPath(p.ID, template.VsockUDS) }

// Snapshot pauses the VM and writes a full snapshot to /vmstate and /mem in
// its chroot. It returns their host paths.
func (p *Proc) Snapshot(ctx context.Context) (string, string, error) {
	api := p.API()
	paused := models.VMStatePaused
	if _, err := api.PatchVMContext(ctx, &operations.PatchVMParams{Body: &models.VM{State: &paused}}); err != nil {
		return "", "", apiErr("pause", err)
	}
	snap, mem := "/"+template.VMStateFile, "/"+template.MemFile
	if _, err := api.CreateSnapshotContext(ctx, &operations.CreateSnapshotParams{Body: &models.SnapshotCreateParams{
		SnapshotType: models.SnapshotCreateParamsSnapshotTypeFull, SnapshotPath: &snap, MemFilePath: &mem,
	}}); err != nil {
		return "", "", apiErr("snapshot", err)
	}
	lay := p.l.Cmd.Layout
	return lay.HostPath(p.ID, snap), lay.HostPath(p.ID, mem), nil
}
