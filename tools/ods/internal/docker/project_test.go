package docker

import (
	"maps"
	"slices"
	"strconv"
	"testing"
)

func TestNormalizeProjectName(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"onyx", "onyx"},
		{"feature-x", "feature-x"},
		{"My.Feature", "myfeature"},
		{"UPPER_CASE", "upper_case"},
		{"has space", "hasspace"},
		{"123-numeric", "123-numeric"},
		{"...", defaultProjectName},
	}
	for _, tt := range tests {
		if got := NormalizeProjectName(tt.input); got != tt.want {
			t.Errorf("NormalizeProjectName(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

func TestFindAvailablePorts_reusesRunningContainerPorts(t *testing.T) {
	// Every container reports host port 2<containerPort>, e.g. 25432.
	calls := fakeDocker(t, `echo "0.0.0.0:2$3"`)

	resolved, err := FindAvailablePorts("proj")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	want := map[string]string{
		"POSTGRES_HOST_PORT":         "25432",
		"REDIS_HOST_PORT":            "26379",
		"OPENSEARCH_HOST_PORT":       "29200",
		"MODEL_SERVER_HOST_PORT":     "29000",
		"OBJECT_STORE_HOST_PORT":     "28333",
		"CODE_INTERPRETER_HOST_PORT": "28000",
	}
	if got := resolved.ComposeEnv(); !maps.Equal(got, want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
	wantCalls := []string{
		"port proj-relational_db-1 5432",
		"port proj-cache-1 6379",
		"port proj-opensearch-1 9200",
		"port proj-inference_model_server-1 9000",
		"port proj-object-store-1 8333",
		"port proj-code-interpreter-1 8000",
	}
	if got := readCalls(t, calls); !slices.Equal(got, wantCalls) {
		t.Fatalf("expected calls %q, got %q", wantCalls, got)
	}
}

func TestFindAvailablePorts_probesWithoutReusingClaimedPorts(t *testing.T) {
	// Only the model server runs, and it holds object-store's default port.
	fakeDocker(t, `[ "$2" = proj-inference_model_server-1 ] && echo 0.0.0.0:9004 && exit 0
exit 1`)

	resolved, err := FindAvailablePorts("proj")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	env := resolved.ComposeEnv()
	if env["MODEL_SERVER_HOST_PORT"] != "9004" {
		t.Fatalf("expected the running model server port 9004, got %q", env["MODEL_SERVER_HOST_PORT"])
	}
	seen := map[string]string{}
	for key, port := range env {
		if other, ok := seen[port]; ok {
			t.Fatalf("%s and %s both got port %s", key, other, port)
		}
		seen[port] = key
	}
	for _, svc := range InfraServices {
		for _, spec := range svc.Ports {
			port, err := strconv.Atoi(env[spec.ComposeVar])
			if err != nil {
				t.Fatalf("%s: %v", spec.ComposeVar, err)
			}
			if spec.ComposeVar != "MODEL_SERVER_HOST_PORT" && (port < spec.DefaultHost || port >= spec.DefaultHost+maxPortScanRange) {
				t.Errorf("%s: expected a port in [%d, %d), got %d", spec.ComposeVar, spec.DefaultHost, spec.DefaultHost+maxPortScanRange, port)
			}
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
	// A spec without an AppVar stays out of the app env.
	resolved.Append(9005, PortSpec{ContainerPort: 9001, DefaultHost: 9005, ComposeVar: "EXAMPLE_CONSOLE_HOST_PORT"})

	want := map[string]string{
		"POSTGRES_PORT":             "5432",
		"REDIS_PORT":                "6379",
		"OPENSEARCH_REST_API_PORT":  "9200",
		"MODEL_SERVER_PORT":         "9000",
		"S3_ENDPOINT_URL":           "http://localhost:9004",
		"CODE_INTERPRETER_BASE_URL": "http://localhost:8000",
	}
	if got := resolved.AppEnv(); !maps.Equal(got, want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
}
