package cmd

import (
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

func TestUpsertEnvFile(t *testing.T) {
	tests := []struct {
		name    string
		initial string
		calls   []map[string]string
		want    string
	}{
		{name: "creates a missing file", calls: []map[string]string{{"FOO": "bar"}}, want: "FOO=bar\n"},
		{name: "replaces a key in place", initial: "A=1\nFOO=old\nB=2\n", calls: []map[string]string{{"FOO": "new"}}, want: "A=1\nFOO=new\nB=2\n"},
		{name: "appends a new key", initial: "EXISTING=value\n", calls: []map[string]string{{"NEW_KEY": "v"}}, want: "EXISTING=value\nNEW_KEY=v\n"},
		{name: "repeated calls keep one line", calls: []map[string]string{{"PORT": "5432"}, {"PORT": "5432"}, {"PORT": "15432"}}, want: "PORT=15432\n"},
		{name: "ignores a commented-out key", initial: "# FOO=old\nBAR=keep\n", calls: []map[string]string{{"FOO": "new"}}, want: "# FOO=old\nBAR=keep\nFOO=new\n"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			envPath := filepath.Join(t.TempDir(), ".env")
			if tt.initial != "" {
				writeFile(t, envPath, tt.initial)
			}
			for _, values := range tt.calls {
				if err := devstack.UpsertEnvFile(envPath, values); err != nil {
					t.Fatalf("UpsertEnvFile(%v): %v", values, err)
				}
			}
			if got := composeReadFile(t, envPath); got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestQueryContainerPorts_usesRunningContainersOnly(t *testing.T) {
	bin := composeFakeBin(t)
	composeFakeTool(t, bin, "docker", `case "$2" in *-relational_db-1|*-object-store-1) echo "0.0.0.0:3$3" ;; *) exit 1 ;; esac`)
	logs := composeCaptureLog(t)

	resolved := queryContainerPorts("proj")

	wantEnv := map[string]string{
		"POSTGRES_HOST_PORT":     "35432",
		"OBJECT_STORE_HOST_PORT": "38333",
	}
	if got := resolved.ComposeEnv(); !maps.Equal(got, wantEnv) {
		t.Fatalf("expected %v, got %v", wantEnv, got)
	}
	wantCalls := []string{
		"port proj-relational_db-1 5432",
		"port proj-cache-1 6379",
		"port proj-opensearch-1 9200",
		"port proj-inference_model_server-1 9000",
		"port proj-object-store-1 8333",
		"port proj-code-interpreter-1 8000",
	}
	if got := composeCalls(t, bin, "docker"); !slices.Equal(got, wantCalls) {
		t.Fatalf("expected %q, got %q", wantCalls, got)
	}
	wantLogs := "level=warning msg=cache: container not running, skipping getting its port.\n" +
		"level=warning msg=opensearch: container not running, skipping getting its port.\n" +
		"level=warning msg=inference_model_server: container not running, skipping getting its port.\n" +
		"level=warning msg=code-interpreter: container not running, skipping getting its port.\n"
	if logs.String() != wantLogs {
		t.Fatalf("expected logs %q, got %q", wantLogs, logs.String())
	}
}

// composeAppEnv is the .vscode/.env content for containers whose host ports
// are the container ports prefixed with 1.
var composeAppEnv = map[string]string{
	"POSTGRES_PORT":             "15432",
	"REDIS_PORT":                "16379",
	"OPENSEARCH_REST_API_PORT":  "19200",
	"MODEL_SERVER_PORT":         "19000",
	"S3_ENDPOINT_URL":           "http://localhost:18333",
	"CODE_INTERPRETER_BASE_URL": "http://localhost:18000",
}

func composeEnvDocker(t *testing.T) string {
	t.Helper()
	bin := composeFakeBin(t)
	composeFakeTool(t, bin, "docker", `echo "0.0.0.0:1$3"`)
	return bin
}

func TestEnvCommand_updatesVSCodeEnvInPlace(t *testing.T) {
	bin := composeEnvDocker(t)
	root := composeRepo(t)
	envPath := filepath.Join(root, ".vscode", ".env")
	writeFile(t, envPath, "CUSTOM_SETTING=x\nPOSTGRES_PORT=1\nS3_LEGACY_ENDPOINT_URL=http://localhost:9005\n")

	command := NewEnvCommand()
	command.SetArgs([]string{})
	if err := command.Execute(); err != nil {
		t.Fatal(err)
	}

	content := composeReadFile(t, envPath)
	if !strings.HasPrefix(content, "CUSTOM_SETTING=x\nPOSTGRES_PORT=15432\n") {
		t.Fatalf("expected existing lines to stay in place, got %q", content)
	}
	// The legacy endpoint is dropped: dev runs the object store only.
	want := maps.Clone(composeAppEnv)
	want["CUSTOM_SETTING"] = "x"
	if got := composeEnvFile(t, content); !maps.Equal(got, want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
	if got := composeCalls(t, bin, "docker"); len(got) != 6 || got[0] != "port ods-proj-relational_db-1 5432" {
		t.Fatalf("expected port queries for project ods-proj, got %q", got)
	}
}

func TestRunEnv_dryRunPrintsWithoutWriting(t *testing.T) {
	composeEnvDocker(t)
	root := composeRepo(t)

	var err error
	stdout := composeCapture(t, &os.Stdout, func() { err = runEnv(true) })

	if err != nil {
		t.Fatal(err)
	}
	if got := composeEnvFile(t, stdout); !maps.Equal(got, composeAppEnv) {
		t.Fatalf("expected %v, got %v", composeAppEnv, got)
	}
	if _, statErr := os.Stat(filepath.Join(root, ".vscode")); !os.IsNotExist(statErr) {
		t.Fatalf("expected no .vscode directory, got %v", statErr)
	}
}

func TestRunEnv_errors(t *testing.T) {
	t.Run("missing selected database leaves dotenv unchanged", func(t *testing.T) {
		bin := composeFakeBin(t)
		composeFakeTool(t, bin, "docker", `case "$2" in *-relational_db-1) exit 1 ;; *) echo "0.0.0.0:1$3" ;; esac`)
		root := composeRepo(t)
		envPath := filepath.Join(root, ".vscode", ".env")
		initial := "POSTGRES_PORT=5432\nS3_LEGACY_ENDPOINT_URL=http://localhost:9005\nSECRET=keep\n"
		writeFile(t, envPath, initial)
		if err := runEnv(false); err == nil || !strings.Contains(err.Error(), "PostgreSQL") {
			t.Fatalf("expected missing selected PostgreSQL error, got %v", err)
		}
		if got := composeReadFile(t, envPath); got != initial {
			t.Fatalf("dotenv changed without selected database: %q", got)
		}
	})

	t.Run("env file is a directory", func(t *testing.T) {
		composeEnvDocker(t)
		root := composeRepo(t)
		envPath := filepath.Join(root, ".vscode", ".env")
		if err := os.MkdirAll(envPath, 0o755); err != nil {
			t.Fatal(err)
		}
		err := runEnv(false)
		want := "Failed to update " + envPath + ": read " + envPath + ": "
		if err == nil || !strings.HasPrefix(err.Error(), want) {
			t.Fatalf("expected error starting with %q, got %v", want, err)
		}
	})

	t.Run("outside a git repo", func(t *testing.T) {
		composeEnvDocker(t)
		composeRepo(t)
		composeNoRepo(t)
		err := runEnv(false)
		if err == nil || !strings.Contains(err.Error(), "not inside a git worktree") {
			t.Fatalf("expected a git root error, got %v", err)
		}
	})
}
