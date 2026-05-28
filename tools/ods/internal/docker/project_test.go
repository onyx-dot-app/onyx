package docker

import (
	"testing"
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

func TestName_defaultsWhenNoFlag(t *testing.T) {
	SetProjectFlags("")
	name := ProjectName()
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
