package cmd

import (
	"errors"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

// devtoolBackendRepo builds a repository with a backend directory and an env
// template, and a fake uv that writes the env it sees to the returned file.
func devtoolBackendRepo(t *testing.T, template string) (root, uvCalls, uvEnv string) {
	t.Helper()
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	binDir := devtoolBinDir(t)
	root = devtoolRepo(t)
	writeFile(t, filepath.Join(root, ".vscode", "env_template.txt"), template)
	writeFile(t, filepath.Join(root, ".vscode", "env.web_template.txt"), "")
	writeFile(t, filepath.Join(root, ".vscode", "launch.json"), `{"configurations":[
		{"name":"API Server","type":"debugpy","request":"launch","module":"uvicorn","cwd":"${workspaceFolder}/backend","envFile":"${workspaceFolder}/.vscode/.env","args":["onyx.main:app","--reload","--port","8080"]},
		{"name":"Model Server","type":"debugpy","request":"launch","module":"uvicorn","cwd":"${workspaceFolder}/backend","envFile":"${workspaceFolder}/.vscode/.env","args":["model_server.main:app","--reload","--port","9000"]}
	]}`)
	writeFile(t, filepath.Join(root, ".venv", "bin", "python"), "#!/bin/sh\nexec uv \"$@\"\n")
	if err := os.Chmod(filepath.Join(root, ".venv", "bin", "python"), 0o755); err != nil {
		t.Fatal(err)
	}
	devtoolFakeTool(t, binDir, "docker", "printf '0.0.0.0:55432\\n'\n")
	if err := os.MkdirAll(filepath.Join(root, "backend"), 0o755); err != nil {
		t.Fatal(err)
	}
	uvEnv = filepath.Join(binDir, "uv.env")
	uvCalls = devtoolFakeTool(t, binDir, "uv", `printf 'FROM_FILE=%s\nSHELL_WINS=%s\n' "$FROM_FILE" "$SHELL_WINS" > "$0.env"`+"\n")
	devtoolUnsetenv(t, devLicenseEnv)
	devtoolUnsetenv(t, "FROM_FILE")
	return root, uvCalls, uvEnv
}

// devtoolFreePort returns a port that nothing listens on right now.
func devtoolFreePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", ":0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	if err := ln.Close(); err != nil {
		t.Fatal(err)
	}
	return port
}

func devtoolReadFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestBackendCommand_runsUvicornWithMergedEnv(t *testing.T) {
	cases := []struct {
		name       string
		subcommand []string
		module     string
	}{
		{"api", []string{"api"}, "onyx.main:app"},
		{"model server", []string{"model_server"}, "model_server.main:app"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			template := "# comment\nFROM_FILE=\"quoted value\"\nSHELL_WINS=file\n"
			root, uvCalls, uvEnv := devtoolBackendRepo(t, template)
			t.Setenv("SHELL_WINS", "shell")
			port := strconv.Itoa(devtoolFreePort(t))

			cmd := NewBackendCommand()
			cmd.SetArgs(append(c.subcommand, "--port", port))
			if err := cmd.Execute(); err != nil {
				t.Fatalf("Execute: %v", err)
			}

			want := []devtoolCall{{Dir: filepath.Join(root, "backend"), Args: []string{"-m", "uvicorn", c.module, "--reload", "--port", port}}}
			if got := devtoolCalls(t, uvCalls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
			if got := devtoolReadFile(t, filepath.Join(root, ".vscode", ".env")); got != template {
				t.Fatalf("expected .env copied from the template, got %q", got)
			}
			wantEnv := "FROM_FILE=quoted value\nSHELL_WINS=shell\n"
			if got := devtoolReadFile(t, uvEnv); got != wantEnv {
				t.Fatalf("expected env %q, got %q", wantEnv, got)
			}
		})
	}
}

func TestRunBackendServicePreparesPythonBeforeLaunch(t *testing.T) {
	for _, service := range []string{"api", "model"} {
		for _, environment := range []string{"missing", "stale"} {
			t.Run(service+"/"+environment, func(t *testing.T) {
				root, _, _ := devtoolBackendRepo(t, "")
				python := filepath.Join(root, ".venv", "bin", "python")
				if environment == "missing" {
					if err := os.RemoveAll(filepath.Join(root, ".venv")); err != nil {
						t.Fatal(err)
					}
				} else {
					writeFile(t, python, "#!/bin/sh\nexit 41\n")
				}
				result := filepath.Join(root, "service-started")
				t.Setenv("ODS_TEST_PYTHON", python)
				t.Setenv("ODS_TEST_SERVICE_RESULT", result)
				devtoolFakeTool(t, os.Getenv("PATH"), "uv", `
[ "$1" = sync ] || exit 42
/bin/mkdir -p "${ODS_TEST_PYTHON%/*}"
printf '#!/bin/sh\nprintf "%%s\\n" "$@" > "$ODS_TEST_SERVICE_RESULT"\n' > "$ODS_TEST_PYTHON"
/bin/chmod +x "$ODS_TEST_PYTHON"
`)
				port := strconv.Itoa(devtoolFreePort(t))
				if err := runBackendService(service, port); err != nil {
					t.Fatalf("start with %s environment: %v", environment, err)
				}
				module := "onyx.main:app"
				if service == "model" {
					module = "model_server.main:app"
				}
				want := "-m\nuvicorn\n" + module + "\n--reload\n--port\n" + port + "\n"
				if got := devtoolReadFile(t, result); got != want {
					t.Fatalf("service arguments=%q, want %q", got, want)
				}
			})
		}
	}
}

func TestBackendCommand_seedsTheDevLicenseBeforeTheAPIOnly(t *testing.T) {
	seed := []string{"run", "python", "-m", "scripts.seed_dev_license"}
	cases := []struct {
		name     string
		service  string
		module   string
		shell    string
		envFile  string
		wantSeed bool
	}{
		{name: "api with a license in the shell", service: "api", module: "onyx.main:app", shell: "license-blob", wantSeed: true},
		{name: "api with a license in .vscode/.env", service: "api", module: "onyx.main:app", envFile: "ONYX_DEV_LICENSE=license-blob\n", wantSeed: true},
		{name: "api with an empty license", service: "api", module: "onyx.main:app"},
		{name: "multi-tenant api with a license", service: "api", module: "onyx.main:app", shell: "license-blob", envFile: "MULTI_TENANT=true\n"},
		{name: "model server with a license", service: "model", module: "model_server.main:app", shell: "license-blob"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			root, uvCalls, _ := devtoolBackendRepo(t, c.envFile)
			if c.shell != "" {
				t.Setenv(devLicenseEnv, c.shell)
			}
			port := strconv.Itoa(devtoolFreePort(t))

			if err := runBackendService(c.service, port); err != nil {
				t.Fatalf("runBackendService: %v", err)
			}

			backendDir := filepath.Join(root, "backend")
			want := []devtoolCall{{Dir: backendDir, Args: []string{"-m", "uvicorn", c.module, "--reload", "--port", port}}}
			if c.wantSeed {
				want = append([]devtoolCall{{Dir: backendDir, Args: seed}}, want...)
			}
			if got := devtoolCalls(t, uvCalls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestRunBackendService_seedOutcomeDecidesTheStart(t *testing.T) {
	seed := []string{"run", "python", "-m", "scripts.seed_dev_license"}
	cases := []struct {
		name    string
		envFile string
		shell   string
		wantErr string
	}{
		// The license is only in the file, so the seed must be handed the merged env.
		{name: "seed accepts the license from .vscode/.env", envFile: "ONYX_DEV_LICENSE=wanted\n"},
		{name: "seed rejects the license", shell: "rejected", wantErr: "Failed to seed the dev license"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			root, _, _ := devtoolBackendRepo(t, c.envFile)
			uvCalls := devtoolFakeTool(t, os.Getenv("PATH"), "uv", `[ "$ONYX_DEV_LICENSE" = wanted ] || exit 4`+"\n")
			if c.shell != "" {
				t.Setenv(devLicenseEnv, c.shell)
			}
			port := strconv.Itoa(devtoolFreePort(t))

			err := runBackendService("api", port)

			backendDir := filepath.Join(root, "backend")
			want := []devtoolCall{{Dir: backendDir, Args: seed}}
			if c.wantErr == "" {
				if err != nil {
					t.Fatalf("runBackendService: %v", err)
				}
				want = append(want, devtoolCall{Dir: backendDir, Args: []string{"-m", "uvicorn", "onyx.main:app", "--reload", "--port", port}})
			} else if err == nil || !strings.Contains(err.Error(), c.wantErr) {
				t.Fatalf("expected an error containing %q, got %v", c.wantErr, err)
			}
			if got := devtoolCalls(t, uvCalls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestRunBackendService_keepsAnExistingEnvFile(t *testing.T) {
	root, _, uvEnv := devtoolBackendRepo(t, "FROM_FILE=template\n")
	envFile := filepath.Join(root, ".vscode", ".env")
	writeFile(t, envFile, "FROM_FILE=edited\n")

	if err := runBackendService("api", strconv.Itoa(devtoolFreePort(t))); err != nil {
		t.Fatalf("runBackendService: %v", err)
	}

	if got := devtoolReadFile(t, envFile); got != "FROM_FILE=edited\n" {
		t.Fatalf("expected the existing .env to be kept, got %q", got)
	}
	if got := devtoolReadFile(t, uvEnv); !strings.HasPrefix(got, "FROM_FILE=edited\n") {
		t.Fatalf("expected uv to see the .env value, got %q", got)
	}
}

func TestRunBackendService_movesOffABusyPort(t *testing.T) {
	_, uvCalls, _ := devtoolBackendRepo(t, "")
	ln, err := net.Listen("tcp", ":0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	busy := ln.Addr().(*net.TCPAddr).Port

	if err := runBackendService("api", strconv.Itoa(busy)); err != nil {
		t.Fatalf("runBackendService: %v", err)
	}

	calls := devtoolCalls(t, uvCalls)
	if len(calls) != 1 {
		t.Fatalf("expected one uv call, got %q", calls)
	}
	args := calls[0].Args
	got, err := strconv.Atoi(args[len(args)-1])
	if err != nil || got <= busy {
		t.Fatalf("expected a port above busy port %d, got %q", busy, calls[0])
	}
}

func TestBackendCommandPublishesThePortAndForwardsArguments(t *testing.T) {
	root, calls, _ := devtoolBackendRepo(t, "")
	port := strconv.Itoa(devtoolFreePort(t))
	cmd := NewBackendCommand()
	cmd.SetArgs([]string{"api", "--port", port, "--", "--host", "127.0.0.1"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	want := []devtoolCall{{Dir: filepath.Join(root, "backend"), Args: []string{"-m", "uvicorn", "onyx.main:app", "--reload", "--port", port, "--host", "127.0.0.1"}}}
	if got := devtoolCalls(t, calls); !reflect.DeepEqual(got, want) {
		t.Fatalf("calls=%v, want %v", got, want)
	}
	target, err := resolveRuntimeTarget()
	if err != nil {
		t.Fatal(err)
	}
	state, err := stackForTarget(target).ReadState()
	if err != nil || state == nil || strconv.Itoa(target.Ports["api"]) != port || len(state.Services) != 1 || state.Services[0].Command[0] != filepath.Join(root, ".venv", "bin", "python") {
		t.Fatalf("target=%+v state=%+v err=%v", target, state, err)
	}
}

func TestBackendAPIRequiresTheSelectedDatabase(t *testing.T) {
	_, calls, _ := devtoolBackendRepo(t, "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\n")
	devtoolFakeTool(t, os.Getenv("PATH"), "docker", "exit 1\n")
	err := runBackendService("api", strconv.Itoa(devtoolFreePort(t)))
	if err == nil || !strings.Contains(err.Error(), "run 'ods stack up' first") {
		t.Fatalf("missing database error=%v", err)
	}
	if got := devtoolCalls(t, calls); len(got) != 0 {
		t.Fatalf("API started without its database: %v", got)
	}
}

func TestRunBackendService_errors(t *testing.T) {
	cases := []struct {
		name  string
		setup func(t *testing.T) string
		port  string
		want  string
		// exitCode is the uv exit code the error must carry, or 0 when the
		// error must not carry one.
		exitCode int
	}{
		{
			name: "outside a repository",
			setup: func(t *testing.T) string {
				devtoolBinDir(t)
				t.Chdir(t.TempDir())
				return ""
			},
			want: "Failed to find git root",
		},
		{
			name: "port is not a number",
			setup: func(t *testing.T) string {
				devtoolBackendRepo(t, "")
				return "http"
			},
			want: `Invalid port "http"`,
		},
		{
			name: "no env file and no template",
			setup: func(t *testing.T) string {
				root, _, _ := devtoolBackendRepo(t, "")
				if err := os.Remove(filepath.Join(root, ".vscode", "env_template.txt")); err != nil {
					t.Fatal(err)
				}
				return ""
			},
			want: "read env template",
		},
		{
			name: ".vscode is a file",
			setup: func(t *testing.T) string {
				root, _, _ := devtoolBackendRepo(t, "")
				vscode := filepath.Join(root, ".vscode")
				if err := os.RemoveAll(vscode); err != nil {
					t.Fatal(err)
				}
				writeFile(t, vscode, "")
				return ""
			},
			want: "not a directory",
		},
		{
			name: "env file line is too long to scan",
			setup: func(t *testing.T) string {
				devtoolBackendRepo(t, "KEY="+strings.Repeat("x", 70_000)+"\n")
				return ""
			},
			want: "token too long",
		},
		{
			name: "Python environment is not installed",
			setup: func(t *testing.T) string {
				root, _, _ := devtoolBackendRepo(t, "")
				if err := os.Remove(filepath.Join(root, ".venv", "bin", "python")); err != nil {
					t.Fatal(err)
				}
				return ""
			},
			want: "Failed to run api",
		},
		{
			name: "uvicorn exits with an error",
			setup: func(t *testing.T) string {
				devtoolBackendRepo(t, "")
				devtoolFakeTool(t, os.Getenv("PATH"), "uv", "exit 3\n")
				return ""
			},
			want:     "Failed to run api: exit status 3",
			exitCode: 3,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			port := c.setup(t)
			if port == "" {
				port = strconv.Itoa(devtoolFreePort(t))
			}

			err := runBackendService("api", port)
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("expected an error containing %q, got %v", c.want, err)
			}
			// exitBackendService passes an exit code through instead of
			// logging, so only the service's own failure may carry one.
			var exitErr *exec.ExitError
			gotCode := 0
			if errors.As(err, &exitErr) {
				gotCode = exitErr.ExitCode()
			}
			if gotCode != c.exitCode {
				t.Fatalf("expected exit code %d, got %d", c.exitCode, gotCode)
			}
		})
	}
}

func TestBackendEnvironmentUsesSharedParser(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env")
	writeFile(t, path, strings.Join([]string{
		"# comment",
		"",
		"PLAIN=value",
		"  SPACED = padded  ",
		`DOUBLE="double quoted"`,
		"SINGLE='single quoted'",
		"URL=postgres://u:p@h/db?x=1",
		"=no_key",
		"no_equals",
		"EMPTY=",
	}, "\n"))

	got, err := devstack.LoadEnvFile(path)
	if err != nil {
		t.Fatalf("loadBackendEnvFile: %v", err)
	}
	want := []string{
		"PLAIN=value",
		"SPACED=padded",
		"DOUBLE=double quoted",
		"SINGLE=single quoted",
		"URL=postgres://u:p@h/db?x=1",
		"EMPTY=",
	}
	if !slices.Equal(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}

	if entries, err := devstack.LoadEnvFile(filepath.Join(t.TempDir(), "missing")); err != nil || len(entries) != 0 {
		t.Fatalf("missing file: entries=%v error=%v", entries, err)
	}
}
