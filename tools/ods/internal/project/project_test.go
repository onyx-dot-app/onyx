package project

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

func TestFindAvailablePort_returnsBaseWhenFree(t *testing.T) {
	base := freePort(t)
	port, err := findAvailablePort(base, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port != base {
		t.Fatalf("expected %d, got %d", base, port)
	}
}

func TestFindAvailablePort_skipsOccupiedPort(t *testing.T) {
	base := freePort(t)
	ln4, err := net.Listen("tcp4", ":"+strconv.Itoa(base))
	if err != nil {
		t.Fatalf("failed to occupy port (ipv4): %v", err)
	}
	defer func() { _ = ln4.Close() }()
	if hasIPv6() {
		ln6, err := net.Listen("tcp6", ":"+strconv.Itoa(base))
		if err != nil {
			t.Fatalf("failed to occupy port (ipv6): %v", err)
		}
		defer func() { _ = ln6.Close() }()
	}

	port, err := findAvailablePort(base, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port <= base {
		t.Fatalf("expected port > %d (occupied), got %d", base, port)
	}
}

func TestFindAvailablePort_skipsClaimedPort(t *testing.T) {
	base := freePort(t)
	claimed := map[int]bool{base: true}
	port, err := findAvailablePort(base, claimed)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port <= base {
		t.Fatalf("expected port > %d (claimed), got %d", base, port)
	}
}

func TestFindAvailablePort_errorWhenAllOccupied(t *testing.T) {
	base := freePort(t)

	var listeners []net.Listener
	defer func() {
		for _, ln := range listeners {
			_ = ln.Close()
		}
	}()

	v6 := hasIPv6()
	for i := 0; i < maxPortScanRange; i++ {
		addr := ":" + strconv.Itoa(base+i)
		ln4, err := net.Listen("tcp4", addr)
		if err != nil {
			t.Fatalf("failed to occupy port %d (ipv4): %v", base+i, err)
		}
		listeners = append(listeners, ln4)
		if v6 {
			ln6, err := net.Listen("tcp6", addr)
			if err != nil {
				t.Fatalf("failed to occupy port %d (ipv6): %v", base+i, err)
			}
			listeners = append(listeners, ln6)
		}
	}

	_, err := findAvailablePort(base, nil)
	if err == nil {
		t.Fatal("expected error when all ports occupied, got nil")
	}
}

func TestName_usesFlag(t *testing.T) {
	SetFlags("custom-project")
	defer SetFlags("")

	if got := Name(); got != "custom-project" {
		t.Fatalf("expected \"custom-project\", got %q", got)
	}
}

func TestName_defaultsWhenNoFlag(t *testing.T) {
	SetFlags("")
	name := Name()
	if name == "" {
		t.Fatal("expected non-empty project name")
	}
}

func TestInfraServiceNames(t *testing.T) {
	names := InfraServiceNames()
	if len(names) != len(InfraServices) {
		t.Fatalf("expected %d names, got %d", len(InfraServices), len(names))
	}
	for i, name := range names {
		if name != InfraServices[i].Name {
			t.Errorf("index %d: expected %q, got %q", i, InfraServices[i].Name, name)
		}
	}
}

func TestResolvedPorts_ComposeEnv(t *testing.T) {
	resolved := NewResolvedPorts()
	for _, svc := range InfraServices {
		for _, spec := range svc.Ports {
			resolved.Append(spec.DefaultHost, spec)
		}
	}

	env := resolved.ComposeEnv()

	expected := map[string]string{
		"POSTGRES_HOST_PORT":         "5432",
		"REDIS_HOST_PORT":            "6379",
		"OPENSEARCH_HOST_PORT":       "9200",
		"MODEL_SERVER_HOST_PORT":     "9000",
		"MINIO_API_HOST_PORT":        "9004",
		"MINIO_CONSOLE_HOST_PORT":    "9005",
		"CODE_INTERPRETER_HOST_PORT": "8000",
	}

	for k, want := range expected {
		got, ok := env[k]
		if !ok {
			t.Errorf("missing key %q", k)
		} else if got != want {
			t.Errorf("%s: expected %q, got %q", k, want, got)
		}
	}
}

func TestResolvedPorts_AppEnv(t *testing.T) {
	resolved := NewResolvedPorts()
	for _, svc := range InfraServices {
		for _, spec := range svc.Ports {
			resolved.Append(spec.DefaultHost, spec)
		}
	}

	env := resolved.AppEnv()

	expected := map[string]string{
		"POSTGRES_PORT":             "5432",
		"REDIS_PORT":                "6379",
		"OPENSEARCH_REST_API_PORT":  "9200",
		"MODEL_SERVER_PORT":         "9000",
		"S3_ENDPOINT_URL":           "http://localhost:9004",
		"CODE_INTERPRETER_BASE_URL": "http://localhost:8000",
	}

	for k, want := range expected {
		got, ok := env[k]
		if !ok {
			t.Errorf("missing key %q", k)
		} else if got != want {
			t.Errorf("%s: expected %q, got %q", k, want, got)
		}
	}

	if _, ok := env["MINIO_CONSOLE_HOST_PORT"]; ok {
		t.Error("MINIO_CONSOLE_HOST_PORT should not appear in AppEnv (empty AppVar)")
	}
}

func TestResolvedPorts_AppEnv_emptyAppVarSkipped(t *testing.T) {
	resolved := NewResolvedPorts()
	resolved.Append(9005, PortSpec{
		ContainerPort: 9001,
		DefaultHost:   9005,
		ComposeVar:    "MINIO_CONSOLE_HOST_PORT",
	})

	env := resolved.AppEnv()
	if len(env) != 0 {
		t.Errorf("expected empty AppEnv for spec with empty AppVar, got %v", env)
	}
}
