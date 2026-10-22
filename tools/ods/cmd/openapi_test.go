package cmd

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// devtoolOpenAPIRepo creates a repository with a fake venv python and returns
// the root and the python call log. The fake drains stdin like real python, so
// writing the embedded script cannot fail with a broken pipe.
func devtoolOpenAPIRepo(t *testing.T, body string) (string, string) {
	t.Helper()
	devtoolBinDir(t)
	root := devtoolRepo(t)
	if err := os.MkdirAll(filepath.Join(root, "backend"), 0o755); err != nil {
		t.Fatal(err)
	}
	venvBin := filepath.Join(root, ".venv", "bin")
	if err := os.MkdirAll(venvBin, 0o755); err != nil {
		t.Fatal(err)
	}
	return root, devtoolFakeTool(t, venvBin, "python", "while read -r _; do :; done\n"+body)
}

func TestOpenAPICommands_runTheScriptWithResolvedPaths(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want func(root string) []string
	}{
		{
			"schema uses the default output",
			[]string{"schema"},
			func(root string) []string {
				return []string{"-", "schema", "-o", root + "/backend/generated/openapi.json"}
			},
		},
		{
			"schema resolves the output from the working directory",
			[]string{"schema", "-o", "out/api.json"},
			func(root string) []string { return []string{"-", "schema", "-o", root + "/web/out/api.json"} },
		},
		{
			"client uses the default paths",
			[]string{"client"},
			func(root string) []string {
				return []string{"-", "client", "-i", root + "/backend/generated/openapi.json", "-o", root + "/backend/generated/onyx_openapi_client"}
			},
		},
		{
			"client keeps an absolute input",
			[]string{"client", "-i", "/abs/api.json", "-o", "gen"},
			func(root string) []string {
				return []string{"-", "client", "-i", "/abs/api.json", "-o", root + "/web/gen"}
			},
		},
		{
			"all passes the client output",
			[]string{"all", "--client-output", "gen"},
			func(root string) []string {
				return []string{"-", "all", "-o", root + "/backend/generated/openapi.json", "--client-output", root + "/web/gen"}
			},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			root, calls := devtoolOpenAPIRepo(t, "")
			if err := os.MkdirAll(filepath.Join(root, "web"), 0o755); err != nil {
				t.Fatal(err)
			}
			t.Chdir(filepath.Join(root, "web"))

			cmd := NewOpenAPICommand()
			cmd.SetArgs(c.args)
			if err := cmd.Execute(); err != nil {
				t.Fatalf("Execute: %v", err)
			}

			want := []devtoolCall{{Dir: filepath.Join(root, "backend"), Args: c.want(root)}}
			if got := devtoolCalls(t, calls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestRunOpenAPI_errors(t *testing.T) {
	runners := []struct {
		name    string
		run     func() error
		prefix  string
		resolve string
	}{
		{"schema", func() error { return runOpenAPISchema(&OpenAPIOptions{}) }, "Failed to generate OpenAPI schema: ", "Failed to resolve output path: "},
		{"client", func() error { return runOpenAPIClient(&OpenAPIOptions{}) }, "Failed to generate Python client: ", "Failed to resolve schema path: "},
		{"client output", func() error { return runOpenAPIClient(&OpenAPIOptions{SchemaPath: "api.json"}) }, "Failed to generate Python client: ", "Failed to resolve client output path: "},
		{"all", func() error { return runOpenAPIAll(&OpenAPIOptions{}) }, "Failed to generate OpenAPI schema and client: ", "Failed to resolve schema path: "},
		{"all client output", func() error { return runOpenAPIAll(&OpenAPIOptions{OutputPath: "api.json"}) }, "Failed to generate OpenAPI schema and client: ", "Failed to resolve client output path: "},
	}
	for _, r := range runners {
		t.Run(r.name+" outside a repository", func(t *testing.T) {
			devtoolBinDir(t)
			gitrelChdirOutsideRepo(t)
			if err := r.run(); err == nil || !strings.HasPrefix(err.Error(), r.resolve) {
				t.Fatalf("expected an error starting with %q, got %v", r.resolve, err)
			}
		})
		t.Run(r.name+" when python fails", func(t *testing.T) {
			devtoolOpenAPIRepo(t, "exit 2\n")
			err := r.run()
			if err == nil || !strings.HasPrefix(err.Error(), r.prefix) {
				t.Fatalf("expected an error starting with %q, got %v", r.prefix, err)
			}
			var exitErr *exec.ExitError
			if !errors.As(err, &exitErr) || exitErr.ExitCode() != 2 {
				t.Fatalf("expected python's exit code 2, got %v", err)
			}
		})
	}
}
