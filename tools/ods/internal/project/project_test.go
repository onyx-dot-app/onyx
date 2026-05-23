package project

import (
	"net"
	"strconv"
	"testing"
)

func TestFindAvailablePort_returnsBaseWhenFree(t *testing.T) {
	port, err := FindAvailablePort(59123)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port != 59123 {
		t.Fatalf("expected 59123, got %d", port)
	}
}

func TestFindAvailablePort_skipsOccupiedPort(t *testing.T) {
	ln4, err := net.Listen("tcp4", ":59200")
	if err != nil {
		t.Fatalf("failed to occupy port (ipv4): %v", err)
	}
	defer func() { _ = ln4.Close() }()
	ln6, err := net.Listen("tcp6", ":59200")
	if err != nil {
		t.Fatalf("failed to occupy port (ipv6): %v", err)
	}
	defer func() { _ = ln6.Close() }()

	port, err := FindAvailablePort(59200)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port == 59200 {
		t.Fatal("expected port != 59200 (occupied), but got 59200")
	}
	if port != 59201 {
		t.Fatalf("expected 59201, got %d", port)
	}
}

func TestFindAvailablePort_errorWhenAllOccupied(t *testing.T) {
	var listeners []net.Listener
	defer func() {
		for _, ln := range listeners {
			_ = ln.Close()
		}
	}()

	base := 59700
	for i := 0; i < maxPortScanRange; i++ {
		addr := ":" + strconv.Itoa(base+i)
		ln4, err := net.Listen("tcp4", addr)
		if err != nil {
			t.Fatalf("failed to occupy port %d (ipv4): %v", base+i, err)
		}
		listeners = append(listeners, ln4)
		ln6, err := net.Listen("tcp6", addr)
		if err != nil {
			t.Fatalf("failed to occupy port %d (ipv6): %v", base+i, err)
		}
		listeners = append(listeners, ln6)
	}

	_, err := FindAvailablePort(base)
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
		AppVar:        "",
		AppFormat:     "",
	})

	env := resolved.AppEnv()
	if len(env) != 0 {
		t.Errorf("expected empty AppEnv for spec with empty AppVar, got %v", env)
	}
}
