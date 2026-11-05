//go:build !linux

// Package vsock is the guest side of AF_VSOCK: a net.Listener and a dialer.
package vsock

import (
	"context"
	"errors"
	"net"
)

// Listen is Linux only.
func Listen(uint32) (net.Listener, error) { return nil, errors.New("vsock needs Linux") }

// Dial is Linux only.
func Dial(context.Context, uint32, uint32) (net.Conn, error) { return nil, errors.New("vsock needs Linux") }
