package devstack

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
)

// DefaultCompound is the launch.json compound that lists every service.
const DefaultCompound = "Run All Onyx Services"

// Profiles name the subsets of the compound that a stack runs.
const (
	ProfileMinimal = "minimal"
	ProfileDefault = "default"
	ProfileFull    = "full"
)

// Profiles lists the valid profile names.
var Profiles = []string{ProfileMinimal, ProfileDefault, ProfileFull}

// profileServices lists the compound entries a profile runs. Full runs the
// whole compound. "Model Server" is added only with LocalModelServer.
var profileServices = map[string][]string{
	ProfileMinimal: {"Web Server", "API Server"},
	ProfileDefault: {
		"Web Server", "API Server",
		"Celery primary", "Celery light", "Celery beat",
		"Celery docfetching", "Celery docprocessing", "Celery user_file_processing",
	},
}

// slackMetricsPort is the fixed port the Slack bot's metrics server binds.
const slackMetricsPort = 8000

// LaunchConfig is one entry of launch.json's "configurations".
type LaunchConfig struct {
	Name              string            `json:"name"`
	Type              string            `json:"type"`
	Request           string            `json:"request"`
	Module            string            `json:"module"`
	Program           string            `json:"program"`
	Args              []string          `json:"args"`
	Cwd               string            `json:"cwd"`
	EnvFile           string            `json:"envFile"`
	Env               map[string]string `json:"env"`
	RuntimeExecutable string            `json:"runtimeExecutable"`
	RuntimeArgs       []string          `json:"runtimeArgs"`
}

// Launch is the parsed launch.json.
type Launch struct {
	Compounds []struct {
		Name           string   `json:"name"`
		Configurations []string `json:"configurations"`
	} `json:"compounds"`
	Configurations []LaunchConfig `json:"configurations"`
}

// LoadLaunch parses .vscode/launch.json, which may hold comments and
// trailing commas.
func LoadLaunch(path string) (*Launch, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var launch Launch
	if err := json.Unmarshal(StripJSONC(data), &launch); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	return &launch, nil
}

// StripJSONC removes // and /* */ comments and trailing commas outside of
// strings, so the result parses as JSON.
func StripJSONC(data []byte) []byte {
	out := make([]byte, 0, len(data))
	var inString, escaped bool
	for i := 0; i < len(data); i++ {
		c := data[i]
		if inString {
			out = append(out, c)
			switch {
			case escaped:
				escaped = false
			case c == '\\':
				escaped = true
			case c == '"':
				inString = false
			}
			continue
		}
		switch {
		case c == '"':
			inString = true
			out = append(out, c)
		case c == '/' && i+1 < len(data) && data[i+1] == '/':
			for i < len(data) && data[i] != '\n' {
				i++
			}
			if i < len(data) {
				out = append(out, '\n')
			}
		case c == '/' && i+1 < len(data) && data[i+1] == '*':
			i += 2
			for i+1 < len(data) && (data[i] != '*' || data[i+1] != '/') {
				i++
			}
			i++
		case c == ',':
			// A comma followed only by whitespace and a closer is dropped.
			j := i + 1
			for j < len(data) && (data[j] == ' ' || data[j] == '\t' || data[j] == '\n' || data[j] == '\r') {
				j++
			}
			if j < len(data) && (data[j] == '}' || data[j] == ']') {
				continue
			}
			out = append(out, c)
		default:
			out = append(out, c)
		}
	}
	return out
}

// Compound returns the configurations a compound lists, in order.
func (l *Launch) Compound(name string) ([]LaunchConfig, error) {
	byName := map[string]LaunchConfig{}
	for _, c := range l.Configurations {
		byName[c.Name] = c
	}
	for _, comp := range l.Compounds {
		if comp.Name != name {
			continue
		}
		var configs []LaunchConfig
		for _, n := range comp.Configurations {
			c, ok := byName[n]
			if !ok {
				return nil, fmt.Errorf("compound %q names missing configuration %q", name, n)
			}
			configs = append(configs, c)
		}
		return configs, nil
	}
	return nil, fmt.Errorf("launch.json has no compound %q", name)
}

// LaunchPlan selects the compound entries for the profile and translates
// them into specs. ports holds the leased app ports (web, api, mcp, model).
func LaunchPlan(root string, launch *Launch, ports map[string]int, env Env, opts Options) ([]Spec, error) {
	configs, err := launch.Compound(DefaultCompound)
	if err != nil {
		return nil, err
	}
	allowed, limited := profileServices[opts.Profile]
	if !limited && opts.Profile != ProfileFull {
		return nil, fmt.Errorf("unknown profile %q (valid: %s)", opts.Profile, strings.Join(Profiles, ", "))
	}
	allowedSet := map[string]bool{}
	for _, name := range allowed {
		allowedSet[name] = true
	}
	var specs []Spec
	for _, c := range configs {
		if c.Name == "Model Server" {
			if !opts.LocalModelServer {
				continue
			}
		} else if limited && !allowedSet[c.Name] {
			continue
		}
		sp, err := Translate(root, c, ports, env)
		if err != nil {
			return nil, err
		}
		specs = append(specs, sp)
	}
	return specs, nil
}

var workspaceVar = regexp.MustCompile(`\$\{workspace(?:Folder|Root)\}`)

func expandWorkspace(value, root string) (string, error) {
	expanded := workspaceVar.ReplaceAllString(value, root)
	if strings.Contains(expanded, "${") {
		return "", fmt.Errorf("unsupported launch.json variable in %q", value)
	}
	return expanded, nil
}

// Translate turns one launch configuration into a runnable spec. The
// environment is the shell, then the configuration's envFile, then its env,
// then the stack overrides. A --port argument of the api, mcp and model
// servers is replaced by the leased port.
func Translate(root string, c LaunchConfig, ports map[string]int, env Env) (Spec, error) {
	if c.Request != "launch" {
		return Spec{}, fmt.Errorf("%s: request %q is not launch", c.Name, c.Request)
	}
	slug := Slugify(c.Name)
	var fileEnv []string
	if c.EnvFile != "" {
		path, err := expandWorkspace(c.EnvFile, root)
		if err != nil {
			return Spec{}, err
		}
		if fileEnv, err = LoadEnvFile(path); err != nil {
			return Spec{}, err
		}
	}
	launchEnv := map[string]string{}
	for k, v := range c.Env {
		expanded, err := expandWorkspace(v, root)
		if err != nil {
			return Spec{}, err
		}
		launchEnv[k] = expanded
	}

	dir := root
	if c.Cwd != "" {
		var err error
		if dir, err = expandWorkspace(c.Cwd, root); err != nil {
			return Spec{}, err
		}
	}

	sp := Spec{Name: c.Name, Slug: slug, Dir: dir, Env: env.With(fileEnv, mapToEnv(launchEnv))}
	switch slug {
	case "web":
		sp.Port = ports["web"]
		sp.Health = fmt.Sprintf("http://localhost:%d/api/auth/type", sp.Port)
	case "api":
		sp.Port = ports["api"]
		sp.Health = fmt.Sprintf("http://localhost:%d/health", sp.Port)
	case "mcp":
		sp.Port = ports["mcp"]
	case "model":
		sp.Port = ports["model"]
		sp.Health = fmt.Sprintf("http://localhost:%d/api/health", sp.Port)
	case "slack-bot":
		sp.Optional = true
		if !bindable(slackMetricsPort) {
			sp.Skip = fmt.Sprintf("its metrics port %d is in use", slackMetricsPort)
		}
	}

	args := make([]string, 0, len(c.Args))
	for i := 0; i < len(c.Args); i++ {
		a, err := expandWorkspace(c.Args[i], root)
		if err != nil {
			return Spec{}, err
		}
		if a == "--port" && sp.Port > 0 && i+1 < len(c.Args) {
			args = append(args, a, fmt.Sprint(sp.Port))
			i++
			continue
		}
		args = append(args, a)
	}

	switch c.Type {
	case "debugpy":
		python := PythonExecutable(root)
		switch {
		case c.Module != "":
			sp.Command = append([]string{python, "-m", c.Module}, args...)
		case c.Program != "":
			program, err := expandWorkspace(c.Program, root)
			if err != nil {
				return Spec{}, err
			}
			sp.Command = append([]string{python, program}, args...)
		default:
			return Spec{}, fmt.Errorf("%s: no module or program", c.Name)
		}
	case "node":
		if c.RuntimeExecutable == "" {
			return Spec{}, fmt.Errorf("%s: no runtimeExecutable", c.Name)
		}
		sp.Command = []string{c.RuntimeExecutable}
		for _, a := range c.RuntimeArgs {
			expanded, err := expandWorkspace(a, root)
			if err != nil {
				return Spec{}, err
			}
			sp.Command = append(sp.Command, expanded)
		}
		sp.Command = append(sp.Command, args...)
	default:
		return Spec{}, fmt.Errorf("%s: unsupported launch type %q", c.Name, c.Type)
	}
	return sp, nil
}

// PythonExecutable is the interpreter of the worktree's uv-managed venv.
func PythonExecutable(root string) string {
	if runtime.GOOS == "windows" {
		return filepath.Join(root, ".venv", "Scripts", "python.exe")
	}
	return filepath.Join(root, ".venv", "bin", "python")
}

// AppPortRequests lists the application ports a profile needs.
func AppPortRequests(opts Options) []PortRequest {
	reqs := []PortRequest{{Name: "web", Preferred: 3000}, {Name: "api", Preferred: 8080}}
	if opts.Profile == ProfileFull {
		reqs = append(reqs, PortRequest{Name: "mcp", Preferred: 8090})
	}
	if opts.LocalModelServer {
		reqs = append(reqs, PortRequest{Name: "model", Preferred: 9000})
	}
	return reqs
}
