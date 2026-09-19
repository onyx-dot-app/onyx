package cmd

import (
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

func TestCheckComposeOptions(t *testing.T) {
	tests := []struct {
		name    string
		profile string
		noEE    bool
		wantErr bool
	}{
		{name: "default profile with EE", profile: "", noEE: false, wantErr: false},
		{name: "default profile without EE", profile: "", noEE: true, wantErr: false},
		{name: "dev profile without EE", profile: "dev", noEE: true, wantErr: false},
		{name: "multitenant profile with EE", profile: "multitenant", noEE: false, wantErr: false},
		{name: "multitenant profile without EE", profile: "multitenant", noEE: true, wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := checkComposeOptions(tt.profile, &ComposeOptions{NoEE: tt.noEE})
			if (err != nil) != tt.wantErr {
				t.Fatalf("checkComposeOptions(%q, NoEE=%v) error = %v, wantErr %v", tt.profile, tt.noEE, err, tt.wantErr)
			}
		})
	}
}

// composeDockerScript answers "docker port <container> <port>" with host port
// 2<port> and records IMAGE_TAG and the working directory of every other call.
func composeDockerScript(bin string) string {
	return `if [ "$1" = port ]; then echo "0.0.0.0:2$3"; exit 0; fi
echo "IMAGE_TAG=${IMAGE_TAG-unset} PWD=$(pwd)" >> "` + filepath.Join(bin, "docker.env") + `"`
}

// composeEnvFile parses KEY=VALUE lines, failing on blank or duplicate lines.
func composeEnvFile(t *testing.T, content string) map[string]string {
	t.Helper()
	if !strings.HasSuffix(content, "\n") {
		t.Fatalf("expected a trailing newline, got %q", content)
	}
	env := map[string]string{}
	for _, line := range strings.Split(strings.TrimSuffix(content, "\n"), "\n") {
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			t.Fatalf("unexpected line %q in %q", line, content)
		}
		if _, dup := env[key]; dup {
			t.Fatalf("duplicate key %q in %q", key, content)
		}
		env[key] = value
	}
	return env
}

const composeInfraServices = "relational_db cache opensearch inference_model_server minio indexing_model_server code-interpreter"

func TestComposeCommand(t *testing.T) {
	tests := []struct {
		name       string
		args       []string
		initialEnv string
		wantCall   string
		wantEnv    map[string]string
		wantTag    string
		wantPorts  bool
	}{
		{
			name:     "default profile starts the stack with EE enabled",
			args:     nil,
			wantCall: "compose -p ods-proj -f docker-compose.yml up -d --wait",
			wantEnv: map[string]string{
				"ENABLE_PAID_ENTERPRISE_EDITION_FEATURES": "true",
				"LICENSE_ENFORCEMENT_ENABLED":             "false",
			},
			wantTag: "unset",
		},
		{
			name:     "dev profile writes the discovered ports and passes every start flag",
			args:     []string{"dev", "--no-ee", "--wait=false", "--force-recreate", "--infra", "--tag", "edge"},
			wantCall: "compose -p ods-proj -f docker-compose.yml -f docker-compose.dev.yml --profile s3-filestore up -d --force-recreate " + composeInfraServices,
			wantEnv: map[string]string{
				"ENABLE_PAID_ENTERPRISE_EDITION_FEATURES": "false",
				"POSTGRES_HOST_PORT":                      "25432",
				"REDIS_HOST_PORT":                         "26379",
				"OPENSEARCH_HOST_PORT":                    "29200",
				"MODEL_SERVER_HOST_PORT":                  "29000",
				"MINIO_API_HOST_PORT":                     "29000",
				"MINIO_CONSOLE_HOST_PORT":                 "29001",
				"CODE_INTERPRETER_HOST_PORT":              "28000",
			},
			wantTag:   "edge",
			wantPorts: true,
		},
		{
			name:       "multitenant down stops infra without touching .env",
			args:       []string{"multitenant", "--down", "--infra"},
			initialEnv: "KEEP=1\n",
			wantCall:   "compose -p ods-proj -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.multitenant.yml --profile s3-filestore down " + composeInfraServices,
			wantEnv:    map[string]string{"KEEP": "1"},
			wantTag:    "unset",
		},
		{
			name:       "default down stops everything",
			args:       []string{"--down"},
			initialEnv: "KEEP=1\n",
			wantCall:   "compose -p ods-proj -f docker-compose.yml down",
			wantEnv:    map[string]string{"KEEP": "1"},
			wantTag:    "unset",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bin := composeFakeBin(t)
			composeFakeTool(t, bin, "docker", composeDockerScript(bin))
			t.Setenv("IMAGE_TAG", "")
			_ = os.Unsetenv("IMAGE_TAG")
			root := composeRepo(t)
			dir := filepath.Join(root, "deployment", "docker_compose")
			envPath := filepath.Join(dir, ".env")
			if tt.initialEnv != "" {
				if err := os.WriteFile(envPath, []byte(tt.initialEnv), 0o644); err != nil {
					t.Fatal(err)
				}
			}

			cmd := NewComposeCommand()
			cmd.SetArgs(tt.args)
			if err := cmd.Execute(); err != nil {
				t.Fatalf("Execute: %v", err)
			}

			calls := composeCalls(t, bin, "docker")
			if len(calls) == 0 {
				t.Fatal("expected docker to run")
			}
			var portCalls int
			for _, call := range calls[:len(calls)-1] {
				if !strings.HasPrefix(call, "port ods-proj-") {
					t.Fatalf("unexpected docker call %q", call)
				}
				portCalls++
			}
			if tt.wantPorts != (portCalls > 0) {
				t.Fatalf("expected port lookups %v, got calls %q", tt.wantPorts, calls)
			}
			if got := calls[len(calls)-1]; got != tt.wantCall {
				t.Fatalf("expected %q, got %q", tt.wantCall, got)
			}
			wantRun := "IMAGE_TAG=" + tt.wantTag + " PWD=" + dir + "\n"
			if got := composeReadFile(t, filepath.Join(bin, "docker.env")); got != wantRun {
				t.Fatalf("expected %q, got %q", wantRun, got)
			}
			if got := composeEnvFile(t, composeReadFile(t, envPath)); !maps.Equal(got, tt.wantEnv) {
				t.Fatalf("expected .env %v, got %v", tt.wantEnv, got)
			}
		})
	}
}

func TestRunCompose_errors(t *testing.T) {
	tests := []struct {
		name       string
		profile    string
		opts       ComposeOptions
		docker     string
		noRepo     bool
		wantPrefix string
		wantDocker bool
	}{
		{name: "invalid profile", profile: "prod", wantPrefix: `Invalid profile "prod". Valid profiles: dev, multitenant`},
		{name: "multitenant without EE", profile: "multitenant", opts: ComposeOptions{NoEE: true}, wantPrefix: "--no-ee cannot be used with the multitenant profile"},
		{name: "docker compose fails", docker: "exit 2", wantPrefix: "Docker compose failed: exit status 2", wantDocker: true},
		{name: "start outside a git repo", noRepo: true, wantPrefix: "Failed to find git root: "},
		{name: "stop outside a git repo", opts: ComposeOptions{Down: true}, noRepo: true, wantPrefix: "Failed to find git root: "},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bin := composeFakeBin(t)
			composeFakeTool(t, bin, "docker", tt.docker)
			var envPath string
			if tt.noRepo {
				composeNoRepo(t)
			} else {
				envPath = filepath.Join(composeRepo(t), "deployment", "docker_compose", ".env")
			}

			err := runCompose(tt.profile, &tt.opts)
			if err == nil || !strings.HasPrefix(err.Error(), tt.wantPrefix) {
				t.Fatalf("expected error starting with %q, got %v", tt.wantPrefix, err)
			}
			if calls := composeCalls(t, bin, "docker"); (calls != nil) != tt.wantDocker {
				t.Fatalf("expected docker to run: %v, got calls %q", tt.wantDocker, calls)
			}
			if envPath != "" && tt.profile != "" {
				if _, err := os.Stat(envPath); !os.IsNotExist(err) {
					t.Fatalf("expected no .env for a rejected profile, got stat error %v", err)
				}
			}
		})
	}
}

func TestSetEnvValue(t *testing.T) {
	tests := []struct {
		name    string
		missing bool
		initial string
		want    string
	}{
		{name: "creates a missing file", missing: true, want: "K=v\n"},
		{name: "fills an empty file", initial: "", want: "K=v\n"},
		{name: "replaces the existing key in place", initial: "A=1\nK=old\nB=2\n", want: "A=1\nK=v\nB=2\n"},
		{name: "appends before the trailing newline", initial: "A=1\n", want: "A=1\nK=v\n"},
		{name: "appends to a file without a trailing newline", initial: "A=1", want: "A=1\nK=v"},
		{name: "does not match a longer key", initial: "KEY=1\n", want: "KEY=1\nK=v\n"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			envPath := filepath.Join(composeRepo(t), "deployment", "docker_compose", ".env")
			if !tt.missing {
				if err := os.WriteFile(envPath, []byte(tt.initial), 0o644); err != nil {
					t.Fatal(err)
				}
			}

			if err := setEnvValue("K", "v"); err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got := composeReadFile(t, envPath); got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestSetEnvValue_errors(t *testing.T) {
	t.Run("unreadable .env", func(t *testing.T) {
		envPath := filepath.Join(composeRepo(t), "deployment", "docker_compose", ".env")
		if err := os.Mkdir(envPath, 0o755); err != nil {
			t.Fatal(err)
		}
		err := setEnvValue("K", "v")
		if err == nil || !strings.HasPrefix(err.Error(), "Failed to read "+envPath+": ") {
			t.Fatalf("expected a read error for %s, got %v", envPath, err)
		}
	})

	t.Run("missing compose directory", func(t *testing.T) {
		dir := filepath.Join(composeRepo(t), "deployment", "docker_compose")
		if err := os.Remove(dir); err != nil {
			t.Fatal(err)
		}
		err := setEnvValue("K", "v")
		if err == nil || !strings.HasPrefix(err.Error(), "Failed to write "+filepath.Join(dir, ".env")+": ") {
			t.Fatalf("expected a write error, got %v", err)
		}
	})
}

func TestLogsCompletion_listsRunningServices(t *testing.T) {
	bin := composeFakeBin(t)
	composeFakeTool(t, bin, "docker", `echo "$(pwd)" > "`+filepath.Join(bin, "pwd")+`"
printf 'api_server\n\nbackground\n'`)
	root := composeRepo(t)

	cmd := NewLogsCommand()
	services, directive := cmd.ValidArgsFunction(cmd, nil, "")

	if want := []string{"api_server", "background"}; !slices.Equal(services, want) {
		t.Fatalf("expected %q, got %q", want, services)
	}
	if directive != cobra.ShellCompDirectiveNoFileComp {
		t.Fatalf("expected no file completion, got %v", directive)
	}
	if got := composeCalls(t, bin, "docker"); !slices.Equal(got, []string{"compose -p ods-proj ps --services"}) {
		t.Fatalf("unexpected docker calls %q", got)
	}
	wantDir := filepath.Join(root, "deployment", "docker_compose") + "\n"
	if got := composeReadFile(t, filepath.Join(bin, "pwd")); got != wantDir {
		t.Fatalf("expected docker to run in %q, got %q", wantDir, got)
	}
}

func TestRunningServiceNames_emptyOnFailure(t *testing.T) {
	t.Run("docker fails", func(t *testing.T) {
		bin := composeFakeBin(t)
		composeFakeTool(t, bin, "docker", "echo api_server; exit 1")
		composeRepo(t)
		if got := runningServiceNames(); got != nil {
			t.Fatalf("expected nil, got %q", got)
		}
	})

	t.Run("outside a git repo", func(t *testing.T) {
		bin := composeFakeBin(t)
		composeFakeTool(t, bin, "docker", "echo api_server")
		composeNoRepo(t)
		if got := runningServiceNames(); got != nil {
			t.Fatalf("expected nil, got %q", got)
		}
		if calls := composeCalls(t, bin, "docker"); calls != nil {
			t.Fatalf("expected docker not to run, got %q", calls)
		}
	})
}

func TestLogsCommand(t *testing.T) {
	tests := []struct {
		name string
		args []string
		want string
	}{
		{name: "follows all services by default", args: nil, want: "compose -p ods-proj -f docker-compose.yml logs -f"},
		{name: "tails selected services", args: []string{"--tail", "100", "api_server", "background"}, want: "compose -p ods-proj -f docker-compose.yml logs -f --tail 100 api_server background"},
		{name: "without follow", args: []string{"--follow=false"}, want: "compose -p ods-proj -f docker-compose.yml logs"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bin := composeFakeBin(t)
			composeFakeTool(t, bin, "docker", "")
			composeRepo(t)

			cmd := NewLogsCommand()
			cmd.SetArgs(tt.args)
			if err := cmd.Execute(); err != nil {
				t.Fatalf("Execute: %v", err)
			}
			if got := composeCalls(t, bin, "docker"); !slices.Equal(got, []string{tt.want}) {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestPullCommand(t *testing.T) {
	tests := []struct {
		name    string
		args    []string
		wantTag string
	}{
		{name: "keeps the default tag", args: nil, wantTag: "unset"},
		{name: "sets IMAGE_TAG", args: []string{"--tag", "edge"}, wantTag: "edge"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bin := composeFakeBin(t)
			composeFakeTool(t, bin, "docker", composeDockerScript(bin))
			t.Setenv("IMAGE_TAG", "")
			_ = os.Unsetenv("IMAGE_TAG")
			root := composeRepo(t)

			cmd := NewPullCommand()
			cmd.SetArgs(tt.args)
			if err := cmd.Execute(); err != nil {
				t.Fatalf("Execute: %v", err)
			}
			want := "compose -p ods-proj -f docker-compose.yml pull"
			if got := composeCalls(t, bin, "docker"); !slices.Equal(got, []string{want}) {
				t.Fatalf("expected %q, got %q", want, got)
			}
			wantRun := "IMAGE_TAG=" + tt.wantTag + " PWD=" + filepath.Join(root, "deployment", "docker_compose") + "\n"
			if got := composeReadFile(t, filepath.Join(bin, "docker.env")); got != wantRun {
				t.Fatalf("expected %q, got %q", wantRun, got)
			}
		})
	}
}

func TestLogsAndPull_returnDockerFailure(t *testing.T) {
	bin := composeFakeBin(t)
	composeFakeTool(t, bin, "docker", "exit 1")
	composeRepo(t)

	const want = "Docker compose failed: exit status 1"
	if err := runComposeLogs(nil, &LogsOptions{}); err == nil || err.Error() != want {
		t.Fatalf("logs: expected %q, got %v", want, err)
	}
	if err := runComposePull(&PullOptions{}); err == nil || err.Error() != want {
		t.Fatalf("pull: expected %q, got %v", want, err)
	}
}
