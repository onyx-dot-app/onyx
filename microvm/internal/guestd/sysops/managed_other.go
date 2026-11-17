//go:build !linux

package sysops

import (
	"context"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
)

// Managed is Linux only.
type Managed struct{}

var _ guestd.ManagedOps = Managed{}

// Probe is Linux only.
func (Managed) Probe(string) (guestd.DevState, error) { return guestd.DevState{}, ErrUnsupported }

// MountedDev is Linux only.
func (Managed) MountedDev(string) (uint64, bool, error) { return 0, false, ErrUnsupported }

// WaitSize is Linux only.
func (Managed) WaitSize(context.Context, string, uint64) error { return ErrUnsupported }

// Flush is Linux only.
func (Managed) Flush(string) error { return ErrUnsupported }

// Mount is Linux only.
func (Managed) Mount(string, string, bool) error { return ErrUnsupported }

// DetachTop is Linux only.
func (Managed) DetachTop(string) error { return ErrUnsupported }

// MountedOn is Linux only.
func (Managed) MountedOn(string, uint64) (bool, error) { return false, ErrUnsupported }
