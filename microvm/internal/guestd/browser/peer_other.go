//go:build !linux

package browser

import "net"

// checkPeerUID does not check: the guest runs on Linux.
func checkPeerUID(net.Conn, uint32) error { return nil }
