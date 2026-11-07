// Package fcvm starts Firecracker VMs under the jailer and restores them from
// a template snapshot.
package fcvm

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"syscall"
	"time"

	httptransport "github.com/go-openapi/runtime/client"
	"github.com/go-openapi/strfmt"

	fcclient "github.com/onyx-dot-app/onyx/microvm/internal/fcapi/client"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/client/operations"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/models"
)

// APIClient returns a Firecracker API client for the socket at sockPath.
func APIClient(sockPath string) *operations.Client {
	tr := httptransport.New("localhost", "/", []string{"http"})
	tr.Transport = &http.Transport{
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "unix", sockPath)
		},
		MaxIdleConns:    1,
		IdleConnTimeout: 30 * time.Second,
	}
	c := fcclient.New(tr, strfmt.Default)
	return c.Operations.(*operations.Client)
}

// WaitSocket waits until a Unix socket accepts connections. Firecracker
// creates api.sock a moment before it listens.
func WaitSocket(ctx context.Context, path string) error {
	for {
		var d net.Dialer
		c, err := d.DialContext(ctx, "unix", path)
		if err == nil {
			return c.Close()
		}
		if !errors.Is(err, syscall.ENOENT) && !errors.Is(err, syscall.ECONNREFUSED) {
			return err
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("wait for %s: %w", path, ctx.Err())
		case <-time.After(2 * time.Millisecond):
		}
	}
}

// LoadSnapshot restores the template snapshot in the chroot and resumes the VM.
func LoadSnapshot(ctx context.Context, c *operations.Client, vmstate, mem string) error {
	backend := models.MemoryBackendBackendTypeFile
	_, err := c.LoadSnapshotContext(ctx, &operations.LoadSnapshotParams{
		Body: &models.SnapshotLoadParams{
			SnapshotPath:     &vmstate,
			MemBackend:       &models.MemoryBackend{BackendType: &backend, BackendPath: &mem},
			ResumeVM:         true,
			NetworkOverrides: []*models.NetworkOverride{},
		},
	})
	return apiErr("load snapshot", err)
}

// RefreshDrive makes Firecracker read the drive size again and tell the
// guest. The guest then sees a grown scratch disk.
func RefreshDrive(ctx context.Context, c *operations.Client, driveID, path string) error {
	_, err := c.PatchGuestDriveByIDContext(ctx, &operations.PatchGuestDriveByIDParams{
		DriveID: driveID,
		Body:    &models.PartialDrive{DriveID: &driveID, PathOnHost: path},
	})
	return apiErr("refresh drive "+driveID, err)
}

// State returns the instance state, for example "Running".
func State(ctx context.Context, c *operations.Client) (string, error) {
	r, err := c.DescribeInstanceContext(ctx, &operations.DescribeInstanceParams{})
	if err != nil {
		return "", apiErr("describe instance", err)
	}
	if r.Payload == nil || r.Payload.State == nil {
		return "", errors.New("describe instance: no state")
	}
	return *r.Payload.State, nil
}

// apiErr adds the Firecracker fault message to an API error.
func apiErr(op string, err error) error {
	if err == nil {
		return nil
	}
	var fault interface{ GetPayload() *models.Error }
	if errors.As(err, &fault) && fault.GetPayload() != nil {
		return fmt.Errorf("%s: %s", op, fault.GetPayload().FaultMessage)
	}
	return fmt.Errorf("%s: %w", op, err)
}
