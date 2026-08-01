// Package resources checks host resources for a deployment: memory and disk
// against the recommended minimums, and a free TCP port for the web server.
package resources

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// MemoryMB returns the memory available to Docker in MB (0 = unknown).
//
// Linux containers share host memory (/proc/meminfo). On macOS, Docker
// Desktop runs a VM whose limit lives in its settings.json; the output of
// `docker system info` (dockerInfo, may be "") is the fallback there and the
// primary source elsewhere.
func MemoryMB(dockerInfo string) int {
	switch runtime.GOOS {
	case "linux":
		if mb := procMeminfoMB(); mb > 0 {
			return mb
		}
	case "darwin":
		if mb := dockerDesktopSettingsMB(); mb > 0 {
			return mb
		}
	}
	return dockerInfoMemoryMB(dockerInfo)
}

func procMeminfoMB() int {
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(data), "\n") {
		if !strings.HasPrefix(line, "MemTotal:") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			return 0
		}
		kb, err := strconv.Atoi(fields[1])
		if err != nil {
			return 0
		}
		return kb / 1024
	}
	return 0
}

func dockerDesktopSettingsMB() int {
	home, err := os.UserHomeDir()
	if err != nil {
		return 0
	}
	path := filepath.Join(home, "Library", "Group Containers", "group.com.docker", "settings.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	var settings struct {
		MemoryMiB int `json:"memoryMiB"`
	}
	if err := json.Unmarshal(data, &settings); err != nil {
		return 0
	}
	return settings.MemoryMiB
}

var totalMemoryPattern = regexp.MustCompile(`(?i)total memory:\s*([0-9.]+)\s*([KMGT]i?B)`)

func dockerInfoMemoryMB(dockerInfo string) int {
	m := totalMemoryPattern.FindStringSubmatch(dockerInfo)
	if m == nil {
		return 0
	}
	value, err := strconv.ParseFloat(m[1], 64)
	if err != nil {
		return 0
	}
	switch strings.ToUpper(strings.TrimSuffix(m[2], "iB")) {
	case "K":
		return int(value / 1024)
	case "M":
		return int(value)
	case "G":
		return int(value * 1024)
	case "T":
		return int(value * 1024 * 1024)
	}
	// Plain "B" suffix (unlikely): treat as bytes.
	return int(value / (1024 * 1024))
}

// FormatMemory renders an MB amount the way install.sh does (~X.YGB above
// 1GB, plain MB below).
func FormatMemory(mb int) string {
	if mb <= 0 {
		return "unknown"
	}
	if mb >= 1024 {
		return fmt.Sprintf("~%.1fGB", float64(mb)/1024)
	}
	return fmt.Sprintf("%dMB", mb)
}

// FindAvailablePort returns the first TCP port >= start that doesn't accept
// connections on localhost (the same connect-probe install.sh uses), falling
// back to start if every port through 65535 is busy.
func FindAvailablePort(start int) int {
	for port := start; port <= 65535; port++ {
		conn, err := net.DialTimeout("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)), 200*time.Millisecond)
		if err != nil {
			return port
		}
		_ = conn.Close()
	}
	return start
}
