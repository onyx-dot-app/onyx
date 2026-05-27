package portutil

import (
	"fmt"
	"net"
)

// IsAvailable reports whether the given TCP port can be bound on the host.
// Uses "tcp" which covers both IPv4 and IPv6 on dual-stack systems.
func IsAvailable(port int) bool {
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		return false
	}
	_ = ln.Close()
	return true
}
