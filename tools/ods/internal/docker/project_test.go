package docker

import (
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestName_usesFlag(t *testing.T) {
	SetProjectFlags("custom-project")
	defer SetProjectFlags("")

	if got := ProjectName(); got != "custom-project" {
		t.Fatalf("expected \"custom-project\", got %q", got)
	}
}

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
		if got := normalizeProjectName(tt.input); got != tt.want {
			t.Errorf("normalizeProjectName(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

func TestName_usesNormalizedGitRootBasename(t *testing.T) {
	SetProjectFlags("")
	repo := filepath.Join(t.TempDir(), "Feature.X")
	if err := os.Mkdir(repo, 0o755); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, repo, "init")
	t.Chdir(repo)

	if got := ProjectName(); got != "featurex" {
		t.Fatalf("expected %q, got %q", "featurex", got)
	}
}

func TestName_defaultsOutsideGitRepo(t *testing.T) {
	SetProjectFlags("")
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)

	if got := ProjectName(); got != defaultProjectName {
		t.Fatalf("expected %q, got %q", defaultProjectName, got)
	}
}

func TestFindAvailablePorts_reusesRunningContainerPorts(t *testing.T) {
	SetProjectFlags("proj")
	t.Cleanup(func() { SetProjectFlags("") })
	// Every container reports host port 2<containerPort>, e.g. 25432.
	calls := fakeDocker(t, `echo "0.0.0.0:2$3"`)

	resolved, err := FindAvailablePorts()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	want := map[string]string{
		"POSTGRES_HOST_PORT":         "25432",
		"REDIS_HOST_PORT":            "26379",
		"OPENSEARCH_HOST_PORT":       "29200",
		"MODEL_SERVER_HOST_PORT":     "29000",
		"MINIO_API_HOST_PORT":        "29000",
		"MINIO_CONSOLE_HOST_PORT":    "29001",
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
		"port proj-minio-1 9000",
		"port proj-minio-1 9001",
		"port proj-code-interpreter-1 8000",
	}
	if got := readCalls(t, calls); !slices.Equal(got, wantCalls) {
		t.Fatalf("expected calls %q, got %q", wantCalls, got)
	}
}

func TestFindAvailablePorts_probesWithoutReusingClaimedPorts(t *testing.T) {
	SetProjectFlags("proj")
	t.Cleanup(func() { SetProjectFlags("") })
	// Only the model server runs, and it holds minio's default API port.
	fakeDocker(t, `[ "$2" = proj-inference_model_server-1 ] && echo 0.0.0.0:9004 && exit 0
exit 1`)

	resolved, err := FindAvailablePorts()
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
