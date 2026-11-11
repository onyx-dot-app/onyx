package devstack

import (
	"errors"
	"io"
	"net"
	"strconv"
	"syscall"
	"testing"
	"time"
)

func TestBindableRejectsLoopbackListeners(t *testing.T) {
	for _, network := range []string{"tcp4", "tcp6"} {
		t.Run(network, func(t *testing.T) {
			address := "127.0.0.1:0"
			if network == "tcp6" {
				address = "[::1]:0"
			}
			listener := listenPortProbe(t, network, address)
			port := listener.Addr().(*net.TCPAddr).Port
			if bindable(port) {
				t.Fatalf("occupied %s loopback port %d is bindable", network, port)
			}
		})
	}
}

func listenPortProbe(t *testing.T, network, address string) net.Listener {
	t.Helper()
	listener, err := net.Listen(network, address)
	if err != nil {
		if network == "tcp6" && (errors.Is(err, syscall.EAFNOSUPPORT) || errors.Is(err, syscall.EPROTONOSUPPORT) || errors.Is(err, syscall.EADDRNOTAVAIL)) {
			t.Skipf("IPv6 unavailable: %v", err)
		}
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = listener.Close() })
	return listener
}

func TestBindableRejectsWildcardListeners(t *testing.T) {
	for _, probe := range []struct{ network, address string }{
		{"tcp4", "0.0.0.0:0"},
		{"tcp6", "[::]:0"},
	} {
		t.Run(probe.network, func(t *testing.T) {
			listener := listenPortProbe(t, probe.network, probe.address)
			port := listener.Addr().(*net.TCPAddr).Port
			if bindable(port) {
				t.Fatalf("occupied %s wildcard port %d is bindable", probe.network, port)
			}
		})
	}
}

func TestBindableAcceptsReleasedPort(t *testing.T) {
	listener := listenPortProbe(t, "tcp4", "127.0.0.1:0")
	port := listener.Addr().(*net.TCPAddr).Port
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	if !bindable(port) {
		t.Fatalf("released port %d is not bindable", port)
	}
}

func TestLeaseAvoidsLoopbackPortAndPreservesForeignListener(t *testing.T) {
	for _, probe := range []struct{ network, host string }{
		{"tcp4", "127.0.0.1"},
		{"tcp6", "::1"},
	} {
		t.Run(probe.network, func(t *testing.T) {
			listener := listenPortProbe(t, probe.network, net.JoinHostPort(probe.host, "0"))
			port := listener.Addr().(*net.TCPAddr).Port
			registry := &Registry{Dir: t.TempDir()}
			ports, err := registry.LeaseFor(t.TempDir(), "", []PortRequest{{Name: "web", Preferred: port}})
			if err != nil {
				t.Fatal(err)
			}
			if ports["web"] == port || ports["web"] <= 0 {
				t.Fatalf("lease did not avoid foreign port %d: %v", port, ports)
			}
			conn, err := net.DialTimeout(probe.network, net.JoinHostPort(probe.host, strconv.Itoa(port)), time.Second)
			if err != nil {
				t.Fatalf("foreign listener stopped accepting connections: %v", err)
			}
			defer func() { _ = conn.Close() }()
			if err := listener.(*net.TCPListener).SetDeadline(time.Now().Add(time.Second)); err != nil {
				t.Fatal(err)
			}
			accepted, err := listener.Accept()
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = accepted.Close() }()
			if err := accepted.SetDeadline(time.Now().Add(time.Second)); err != nil {
				t.Fatal(err)
			}
			if err := conn.SetDeadline(time.Now().Add(time.Second)); err != nil {
				t.Fatal(err)
			}
			if _, err := accepted.Write([]byte("still running")); err != nil {
				t.Fatal(err)
			}
			response := make([]byte, len("still running"))
			if _, err := io.ReadFull(conn, response); err != nil || string(response) != "still running" {
				t.Fatalf("foreign listener no longer serves data: %q, %v", response, err)
			}
		})
	}
}
