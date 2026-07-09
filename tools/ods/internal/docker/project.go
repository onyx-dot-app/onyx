package docker

import (
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
	"unicode"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/portutil"
)

const (
	defaultProjectName = "onyx"
	maxPortScanRange   = 100
)

// PortSpec describes a single port exposed by an infrastructure service.
type PortSpec struct {
	ContainerPort int    // port inside the container (e.g., 5432)
	DefaultHost   int    // default host port when no offset is needed
	ComposeVar    string // env var for docker-compose.dev.yml (e.g., "POSTGRES_HOST_PORT")
	AppVar        string // env var for .vscode/.env (empty = not written to app env)
	AppFormat     string // format string for AppVar value (empty = "%d")
}

// ServiceSpec describes an infrastructure service managed by Docker Compose.
type ServiceSpec struct {
	Name  string // docker compose service name (e.g., "relational_db")
	Ports []PortSpec
}

// InfraServices is the single source of truth for infrastructure dependencies.
// compose, env, and port discovery all derive from this list.
var InfraServices = []ServiceSpec{
	{Name: "relational_db", Ports: []PortSpec{
		{ContainerPort: 5432, DefaultHost: 5432, ComposeVar: "POSTGRES_HOST_PORT", AppVar: "POSTGRES_PORT"},
	}},
	{Name: "cache", Ports: []PortSpec{
		{ContainerPort: 6379, DefaultHost: 6379, ComposeVar: "REDIS_HOST_PORT", AppVar: "REDIS_PORT"},
	}},
	{Name: "opensearch", Ports: []PortSpec{
		{ContainerPort: 9200, DefaultHost: 9200, ComposeVar: "OPENSEARCH_HOST_PORT", AppVar: "OPENSEARCH_REST_API_PORT"},
	}},
	{Name: "inference_model_server", Ports: []PortSpec{
		{ContainerPort: 9000, DefaultHost: 9000, ComposeVar: "MODEL_SERVER_HOST_PORT", AppVar: "MODEL_SERVER_PORT"},
	}},
	{Name: "minio", Ports: []PortSpec{
		{ContainerPort: 9000, DefaultHost: 9004, ComposeVar: "MINIO_API_HOST_PORT", AppVar: "S3_ENDPOINT_URL", AppFormat: "http://localhost:%d"},
		{ContainerPort: 9001, DefaultHost: 9005, ComposeVar: "MINIO_CONSOLE_HOST_PORT"},
	}},
	{Name: "indexing_model_server", Ports: []PortSpec{}},
	{Name: "code-interpreter", Ports: []PortSpec{
		{ContainerPort: 8000, DefaultHost: 8000, ComposeVar: "CODE_INTERPRETER_HOST_PORT", AppVar: "CODE_INTERPRETER_BASE_URL", AppFormat: "http://localhost:%d"},
	}},
}

// InfraServiceNames returns the Docker Compose service names for all
// infrastructure services.
func InfraServiceNames() []string {
	names := make([]string, len(InfraServices))
	for i, s := range InfraServices {
		names[i] = s.Name
	}
	return names
}

// ResolvedPorts holds the discovered host port for each PortSpec, in the same
// order as InfraServices and their Ports slices.
type ResolvedPorts struct {
	ports []int
	specs []PortSpec
}

func NewResolvedPorts() *ResolvedPorts {
	return &ResolvedPorts{}
}

func (r *ResolvedPorts) Append(port int, spec PortSpec) {
	r.ports = append(r.ports, port)
	r.specs = append(r.specs, spec)
}

// ComposeEnv returns env vars for docker-compose.dev.yml (e.g.,
// POSTGRES_HOST_PORT=5432).
func (r *ResolvedPorts) ComposeEnv() map[string]string {
	env := make(map[string]string, len(r.specs))
	for i, spec := range r.specs {
		env[spec.ComposeVar] = strconv.Itoa(r.ports[i])
	}
	return env
}

// AppEnv returns env vars for .vscode/.env (e.g., POSTGRES_PORT=5432,
// S3_ENDPOINT_URL=http://localhost:9004). Specs with an empty AppVar are
// skipped.
func (r *ResolvedPorts) AppEnv() map[string]string {
	env := make(map[string]string)
	for i, spec := range r.specs {
		if spec.AppVar == "" {
			continue
		}
		format := spec.AppFormat
		if format == "" {
			format = "%d"
		}
		env[spec.AppVar] = fmt.Sprintf(format, r.ports[i])
	}
	return env
}

var flagProject string

// SetFlags stores CLI flag values for project resolution. Called once from the
// root command's PersistentPreRun.
func SetProjectFlags(project string) {
	flagProject = project
}

// ProjectName returns the Docker Compose project name. Uses --project if set,
// otherwise the basename of the git working tree root (e.g. "onyx" for the main
// checkout, "feature-x" for a worktree at .../feature-x). The result is
// normalized to satisfy Docker Compose's naming rules (lowercase alphanumeric,
// hyphens, and underscores).
func ProjectName() string {
	if flagProject != "" {
		return normalizeProjectName(flagProject)
	}
	root, err := paths.GitRoot()
	if err != nil {
		return defaultProjectName
	}
	return normalizeProjectName(filepath.Base(root))
}

// normalizeProjectName converts a string into a valid Docker Compose project
// name: lowercase, keeping only alphanumeric characters, hyphens, and
// underscores. Characters that don't match are dropped.
func normalizeProjectName(name string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(name) {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '-' || r == '_' {
			b.WriteRune(r)
		}
	}
	if b.Len() == 0 {
		return defaultProjectName
	}
	return b.String()
}

// FindAvailablePorts resolves host ports for each port spec in InfraServices.
// For each port it first checks whether the project's container is already
// running with a mapped host port (via ``docker port``) and reuses it. Only
// when the container is not running does it probe for a free port. A global
// claimed set prevents cross-service collisions (e.g., inference_model_server
// and minio both defaulting near port 9000).
func FindAvailablePorts() (*ResolvedPorts, error) {
	resolved := NewResolvedPorts()
	claimed := make(map[int]bool)
	projName := ProjectName()

	for _, svc := range InfraServices {
		container := fmt.Sprintf("%s-%s-1", projName, svc.Name)
		for _, spec := range svc.Ports {
			if hp, err := GetHostPort(container, spec.ContainerPort); err == nil {
				claimed[hp] = true
				resolved.Append(hp, spec)
				continue
			}

			port, err := portutil.FindAvailable(spec.DefaultHost, maxPortScanRange, claimed)
			if err != nil {
				return nil, fmt.Errorf("%s port %d: %w", svc.Name, spec.ContainerPort, err)
			}
			claimed[port] = true
			resolved.Append(port, spec)
		}
	}

	return resolved, nil
}
