package portutil

import (
	"fmt"
	"net"
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
)

// IsAvailable reports whether the given TCP port can be bound on the host.
func IsAvailable(port int) bool {
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		return false
	}
	_ = ln.Close()
	return true
}

// FindAvailable scans TCP ports starting from base up to base+maxRange-1,
// returning the first port that is bindable and not in the claimed set. Pass
// nil for claimed if cross-caller deduplication is not needed. When the base
// port is occupied, logs a warning identifying the process holding it and the
// fallback port chosen.
func FindAvailable(base, maxRange int, claimed map[int]bool) (int, error) {
	if !claimed[base] && IsAvailable(base) {
		return base, nil
	}

	proc := ProcessOnPort(base)

	for port := base + 1; port < base+maxRange; port++ {
		if claimed[port] {
			continue
		}
		if !IsAvailable(port) {
			continue
		}
		log.Warnf("Port %d is in use by %s, using available port %d instead.", base, proc, port)
		return port, nil
	}
	return 0, fmt.Errorf("no available port found in range %d-%d", base, base+maxRange-1)
}

// ProcessOnPort returns a human-readable description of the process listening
// on the given port (e.g. "uvicorn (PID 12345)"). Falls back to a generic
// string when the process cannot be identified.
func ProcessOnPort(port int) string {
	out, err := exec.Command("lsof", "-i", fmt.Sprintf(":%d", port), "-t").Output()
	if err != nil || len(strings.TrimSpace(string(out))) == 0 {
		return "an unknown process"
	}
	pid := strings.Split(strings.TrimSpace(string(out)), "\n")[0]
	nameOut, err := exec.Command("ps", "-p", pid, "-o", "comm=").Output()
	if err != nil || len(strings.TrimSpace(string(nameOut))) == 0 {
		return fmt.Sprintf("process (PID %s)", pid)
	}
	return fmt.Sprintf("%s (PID %s)", strings.TrimSpace(string(nameOut)), pid)
}
