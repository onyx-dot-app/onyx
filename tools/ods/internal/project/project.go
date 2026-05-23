package project

import (
	"fmt"
	"net"
	"path/filepath"
	"strconv"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
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
		{5432, 5432, "POSTGRES_HOST_PORT", "POSTGRES_PORT", ""},
	}},
	{Name: "cache", Ports: []PortSpec{
		{6379, 6379, "REDIS_HOST_PORT", "REDIS_PORT", ""},
	}},
	{Name: "opensearch", Ports: []PortSpec{
		{9200, 9200, "OPENSEARCH_HOST_PORT", "OPENSEARCH_REST_API_PORT", ""},
	}},
	{Name: "inference_model_server", Ports: []PortSpec{
		{9000, 9000, "MODEL_SERVER_HOST_PORT", "MODEL_SERVER_PORT", ""},
	}},
	{Name: "minio", Ports: []PortSpec{
		{9000, 9004, "MINIO_API_HOST_PORT", "S3_ENDPOINT_URL", "http://localhost:%d"},
		{9001, 9005, "MINIO_CONSOLE_HOST_PORT", "", ""},
	}},
	{Name: "indexing_model_server", Ports: []PortSpec{}},
	{Name: "code-interpreter", Ports: []PortSpec{
		{8000, 8000, "CODE_INTERPRETER_HOST_PORT", "CODE_INTERPRETER_BASE_URL", "http://localhost:%d"},
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
func SetFlags(project string) {
	flagProject = project
}

// Name returns the Docker Compose project name. Uses --project if set,
// otherwise the basename of the git working tree root (e.g. "onyx" for the main
// checkout, "feature-x" for a worktree at .../feature-x).
func Name() string {
	if flagProject != "" {
		return flagProject
	}
	root, err := paths.GitRoot()
	if err != nil {
		return defaultProjectName
	}
	return filepath.Base(root)
}

// FindAvailablePort probes TCP ports starting from base, incrementing by 1, and
// returns the first port that can be bound on both IPv4 and IPv6. Both must
// succeed because Docker Desktop on macOS binds on IPv6 (via its VM), which
// net.Listen on 127.0.0.1 alone would not detect. Gives up after
// maxPortScanRange attempts.
func FindAvailablePort(base int) (int, error) {
	for port := base; port < base+maxPortScanRange; port++ {
		if !canBind("tcp4", port) || !canBind("tcp6", port) {
			continue
		}
		return port, nil
	}
	return 0, fmt.Errorf("no available port found in range %d-%d", base, base+maxPortScanRange-1)
}

func canBind(network string, port int) bool {
	ln, err := net.Listen(network, fmt.Sprintf(":%d", port))
	if err != nil {
		return false
	}
	_ = ln.Close()
	return true
}

// FindAvailablePorts scans for a free host port for each port spec in
// InfraServices. Within a service, later ports scan starting above earlier
// resolved ports to avoid collisions (e.g., MinIO API and console).
func FindAvailablePorts() (*ResolvedPorts, error) {
	resolved := NewResolvedPorts()

	for _, svc := range InfraServices {
		highestInService := 0
		for _, spec := range svc.Ports {
			base := spec.DefaultHost
			if base <= highestInService {
				base = highestInService + 1
			}
			port, err := FindAvailablePort(base)
			if err != nil {
				return nil, fmt.Errorf("%s port %d: %w", svc.Name, spec.ContainerPort, err)
			}
			resolved.Append(port, spec)
			if port > highestInService {
				highestInService = port
			}
		}
	}

	return resolved, nil
}
