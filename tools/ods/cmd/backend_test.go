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
)

// devtoolBackendRepo builds a repository with a backend directory and an env
// template, and a fake uv that writes the env it sees to the returned file.
func devtoolBackendRepo(t *testing.T, template string) (root, uvCalls, uvEnv string) {
	t.Helper()
	binDir := devtoolBinDir(t)
	root = devtoolRepo(t)
	writeFile(t, filepath.Join(root, ".vscode", "env_template.txt"), template)
	if err := os.MkdirAll(filepath.Join(root, "backend"), 0o755); err != nil {
		t.Fatal(err)
	}
	uvEnv = filepath.Join(binDir, "uv.env")
	uvCalls = devtoolFakeTool(t, binDir, "uv", `printf 'FROM_FILE=%s\nSHELL_WINS=%s\nEE=%s\nLICENSE=%s\n' `+
		`"$FROM_FILE" "$SHELL_WINS" "${ENABLE_PAID_ENTERPRISE_EDITION_FEATURES-unset}" "${LICENSE_ENFORCEMENT_ENABLED-unset}" > "$0.env"`+"\n")
	devtoolUnsetenv(t, "ENABLE_PAID_ENTERPRISE_EDITION_FEATURES")
	devtoolUnsetenv(t, "LICENSE_ENFORCEMENT_ENABLED")
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
		wantEE     string
	}{
		{"api with EE", []string{"api"}, "onyx.main:app", "EE=true\nLICENSE=false\n"},
		{"model server without EE", []string{"model_server", "--no-ee"}, "model_server.main:app", "EE=false\nLICENSE=unset\n"},
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

			want := []devtoolCall{{Dir: filepath.Join(root, "backend"), Args: []string{"run", "uvicorn", c.module, "--reload", "--port", port}}}
			if got := devtoolCalls(t, uvCalls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
			if got := devtoolReadFile(t, filepath.Join(root, ".vscode", ".env")); got != template {
				t.Fatalf("expected .env copied from the template, got %q", got)
			}
			wantEnv := "FROM_FILE=quoted value\nSHELL_WINS=shell\n" + c.wantEE
			if got := devtoolReadFile(t, uvEnv); got != wantEnv {
				t.Fatalf("expected env %q, got %q", wantEnv, got)
			}
		})
	}
}

func TestRunBackendService_keepsAnExistingEnvFile(t *testing.T) {
	root, _, uvEnv := devtoolBackendRepo(t, "FROM_FILE=template\n")
	envFile := filepath.Join(root, ".vscode", ".env")
	writeFile(t, envFile, "FROM_FILE=edited\n")

	if err := runBackendService("api", "onyx.main:app", strconv.Itoa(devtoolFreePort(t)), &BackendOptions{}); err != nil {
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

	if err := runBackendService("api", "onyx.main:app", strconv.Itoa(busy), &BackendOptions{}); err != nil {
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
			want: "Failed to read env template",
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
			want: "Failed to stat env file",
		},
		{
			name: "env file line is too long to scan",
			setup: func(t *testing.T) string {
				devtoolBackendRepo(t, "KEY="+strings.Repeat("x", 70_000)+"\n")
				return ""
			},
			want: "Failed to read env file",
		},
		{
			name: "uv is not installed",
			setup: func(t *testing.T) string {
				devtoolBackendRepo(t, "")
				if err := os.Remove(filepath.Join(os.Getenv("PATH"), "uv")); err != nil {
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

			err := runBackendService("api", "onyx.main:app", port, &BackendOptions{})
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

func TestLoadBackendEnvFile_parsesEntries(t *testing.T) {
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

	got, err := loadBackendEnvFile(path)
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

	if _, err := loadBackendEnvFile(filepath.Join(t.TempDir(), "missing")); err == nil || !strings.Contains(err.Error(), "Failed to open env file") {
		t.Fatalf("expected an open error, got %v", err)
	}
}
