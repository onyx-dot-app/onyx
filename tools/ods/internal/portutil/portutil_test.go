package portutil

import (
	"net"
	"strconv"
	"testing"
)

func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", ":0")
	if err != nil {
		t.Fatalf("failed to find a free port: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()
	return port
}

func TestFindAvailable_returnsBaseWhenFree(t *testing.T) {
	base := freePort(t)
	port, err := FindAvailable(base, 100, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port != base {
		t.Fatalf("expected %d, got %d", base, port)
	}
}

func TestFindAvailable_skipsOccupiedPort(t *testing.T) {
	base := freePort(t)
	ln, err := net.Listen("tcp", ":"+strconv.Itoa(base))
	if err != nil {
		t.Fatalf("failed to occupy port: %v", err)
	}
	defer func() { _ = ln.Close() }()

	port, err := FindAvailable(base, 100, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port <= base {
		t.Fatalf("expected port > %d (occupied), got %d", base, port)
	}
}

func TestFindAvailable_skipsClaimedPort(t *testing.T) {
	base := freePort(t)
	claimed := map[int]bool{base: true}
	port, err := FindAvailable(base, 100, claimed)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port <= base {
		t.Fatalf("expected port > %d (claimed), got %d", base, port)
	}
}

func TestFindAvailable_errorWhenAllOccupied(t *testing.T) {
	base := freePort(t)
	maxRange := 100

	var listeners []net.Listener
	defer func() {
		for _, ln := range listeners {
			_ = ln.Close()
		}
	}()

	for i := 0; i < maxRange; i++ {
		ln, err := net.Listen("tcp", ":"+strconv.Itoa(base+i))
		if err != nil {
			// The port is already held by another process. That still
			// counts as occupied for the purposes of this test, so leave
			// it be rather than failing.
			continue
		}
		listeners = append(listeners, ln)
	}

	_, err := FindAvailable(base, maxRange, nil)
	if err == nil {
		t.Fatal("expected error when all ports occupied, got nil")
	}
}
