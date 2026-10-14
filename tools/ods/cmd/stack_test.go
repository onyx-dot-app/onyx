//go:build !windows

package cmd

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

// stackTestRepo builds a worktree with the directories the stack provider
// touches and a fake docker, uv, bun, tail and alembic. It returns the root
// and the call logs by tool name.
func stackTestRepo(t *testing.T) (root string, calls map[string]string) {
	t.Helper()
	binDir := devtoolBinDir(t)
	// The process manager identifies services with ps.
	ps, err := exec.LookPath("/bin/ps")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(ps, filepath.Join(binDir, "ps")); err != nil {
		t.Fatal(err)
	}
	root = devtoolRepo(t)
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	for _, dir := range []string{".vscode", "backend", "web", filepath.Join("web", "node_modules"), filepath.Join("deployment", "docker_compose"), filepath.Join(".venv", "bin")} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	writeFile(t, filepath.Join(root, ".vscode", "env_template.txt"), "GEN_AI_API_KEY=<REPLACE THIS>\n")
	writeFile(t, filepath.Join(root, ".vscode", "env.web_template.txt"), "AUTH_TYPE=basic\n")
	writeFile(t, filepath.Join(root, ".vscode", ".env"), "S3_LEGACY_ENDPOINT_URL=http://localhost:9005\nKEEP=1\n")
	writeFile(t, filepath.Join(root, "web", "node_modules", "keep"), "")
	writeFile(t, filepath.Join(root, "web", "bun.lock"), "{}")

	calls = map[string]string{}
	// docker port answers for the relational_db container only.
	calls["docker"] = devtoolFakeTool(t, binDir, "docker", `
if [ "$1" = port ]; then
  case "$2" in *relational_db*) echo "0.0.0.0:5555"; exit 0;; *) exit 1;; esac
fi
if [ "$1" = ps ]; then echo owned-inference-container; fi
exit 0
`)
	for _, tool := range []string{"uv", "bun", "tail"} {
		calls[tool] = devtoolFakeTool(t, binDir, tool, "exit 0\n")
	}
	alembic := filepath.Join(root, ".venv", "bin", "alembic")
	writeFile(t, alembic, "#!/bin/sh\nprintf '%s\\0' \"$#\" \"$@\" >> \"$0.calls\"\nprintf 'HOST=%s PORT=%s\\n' \"$POSTGRES_HOST\" \"$POSTGRES_PORT\" > \"$0.env\"\n")
	if err := os.Chmod(alembic, 0o755); err != nil {
		t.Fatal(err)
	}
	calls["alembic"] = alembic + ".env"
	return root, calls
}

func TestStackProvider_infraPortsAndEnv(t *testing.T) {
	root, _ := stackTestRepo(t)
	stack, provider := openStack()
	if stack.Root != root || stack.Project != devstack.ProjectName(root) {
		t.Fatalf("stack %+v", stack)
	}

	reqs, err := provider.InfraPorts()
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]devstack.PortRequest{}
	for _, r := range reqs {
		byName[r.Name] = r
	}
	if pg := byName["POSTGRES_HOST_PORT"]; pg.Fixed != 5555 || pg.Preferred != 5432 {
		t.Errorf("postgres request %+v", pg)
	}
	if redis := byName["REDIS_HOST_PORT"]; redis.Fixed != 0 || redis.Preferred != 6379 {
		t.Errorf("redis request %+v", redis)
	}

	env := provider.InfraEnv(map[string]int{"POSTGRES_HOST_PORT": 5555, "OBJECT_STORE_HOST_PORT": 9010, "MODEL_SERVER_HOST_PORT": 9001, "web": 3000})
	want := map[string]string{"POSTGRES_PORT": "5555", "S3_ENDPOINT_URL": "http://localhost:9010", "MODEL_SERVER_PORT": "9001"}
	if !reflect.DeepEqual(env, want) {
		t.Errorf("InfraEnv = %v, want %v", env, want)
	}

	app := provider.AppPorts(devstack.Options{Profile: devstack.ProfileFull, LocalModelServer: true})
	var names []string
	for _, r := range app {
		names = append(names, r.Name)
	}
	if !reflect.DeepEqual(names, []string{"web", "api", "mcp", "model", "celery-primary-metrics", "celery-light-metrics", "celery-docfetching-metrics", "celery-docprocessing-metrics", "celery-heavy-metrics", "celery-scheduled_tasks-metrics"}) {
		t.Errorf("app ports %v", names)
	}
}

func TestStackProvider_composeUpWritesPortsAndExcludesLocalModel(t *testing.T) {
	root, calls := stackTestRepo(t)
	stack, provider := openStack()

	ports := map[string]int{"POSTGRES_HOST_PORT": 5555, "REDIS_HOST_PORT": 6380, "web": 3000}
	if err := provider.ComposeUp(context.Background(), ports, devstack.Options{LocalModelServer: true}); err != nil {
		t.Fatal(err)
	}
	composeEnv := devtoolReadFile(t, filepath.Join(root, "deployment", "docker_compose", ".env"))
	for _, want := range []string{"POSTGRES_HOST_PORT=5555\n", "REDIS_HOST_PORT=6380\n", "MINIO_REPLICAS=0\n"} {
		if !strings.Contains(composeEnv, want) {
			t.Errorf("compose .env lacks %q:\n%s", want, composeEnv)
		}
	}
	var up []string
	for _, c := range devtoolCalls(t, calls["docker"]) {
		if len(c.Args) > 1 && c.Args[0] == "compose" && slices.Contains(c.Args, "up") {
			up = c.Args
		}
	}
	if up == nil {
		t.Fatal("docker compose up was not run")
	}
	for _, want := range []string{"-p", stack.Project, "--wait", "relational_db", "cache"} {
		if !slices.Contains(up, want) {
			t.Errorf("compose up args lack %q: %v", want, up)
		}
	}
	if slices.Contains(up, "inference_model_server") {
		t.Errorf("compose up started the inference server with a local model server: %v", up)
	}
	var found, stopped bool
	for _, call := range devtoolCalls(t, calls["docker"]) {
		if len(call.Args) > 0 && call.Args[0] == "ps" {
			found = slices.Contains(call.Args, "label=com.docker.compose.project="+stack.Project) && slices.Contains(call.Args, "label=com.docker.compose.service=inference_model_server")
		}
		if slices.Equal(call.Args, []string{"stop", "owned-inference-container"}) {
			stopped = true
		}
	}
	if !found || !stopped {
		t.Fatal("local model mode did not stop only the project-scoped inference container")
	}
	env := devtoolReadFile(t, filepath.Join(root, ".vscode", ".env"))
	if strings.Contains(env, "S3_LEGACY_ENDPOINT_URL") || !strings.Contains(env, "KEEP=1") {
		t.Errorf(".vscode/.env after compose up:\n%s", env)
	}

	if err := provider.ComposeDown(context.Background()); err != nil {
		t.Fatal(err)
	}
	last := devtoolCalls(t, calls["docker"])
	if args := last[len(last)-1].Args; !slices.Contains(args, "down") {
		t.Errorf("compose down args %v", args)
	}
}

func TestStackProvider_prepareAndMigrate(t *testing.T) {
	_, calls := stackTestRepo(t)
	_, provider := openStack()

	if err := provider.Prepare(context.Background()); err != nil {
		t.Fatal(err)
	}
	if uv := devtoolCalls(t, calls["uv"]); len(uv) != 1 || !reflect.DeepEqual(uv[0].Args, []string{"sync", "--frozen"}) {
		t.Errorf("uv calls %v", uv)
	}
	if docker := devtoolCalls(t, calls["docker"]); len(docker) == 0 || docker[0].Args[0] != "info" {
		t.Errorf("docker calls %v", docker)
	}

	env := []string{"POSTGRES_HOST=localhost", "POSTGRES_PORT=5555"}
	if err := provider.Migrate(context.Background(), env); err != nil {
		t.Fatal(err)
	}
	if got := devtoolReadFile(t, calls["alembic"]); got != "HOST=localhost PORT=5555\n" {
		t.Errorf("alembic env %q", got)
	}
}

func TestStackProvider_prepareReportsMissingTool(t *testing.T) {
	root, _ := stackTestRepo(t)
	_, provider := openStack()
	if err := os.Remove(filepath.Join(filepath.Dir(os.Getenv("PATH")), filepath.Base(os.Getenv("PATH")), "bun")); err != nil {
		t.Fatal(err)
	}
	err := provider.Prepare(context.Background())
	if err == nil || !strings.Contains(err.Error(), "bun is not installed") {
		t.Errorf("Prepare in %s: %v", root, err)
	}
}

func TestStackPlanCommand_printsResolvedServices(t *testing.T) {
	root, _ := stackTestRepo(t)
	writeFile(t, filepath.Join(root, ".vscode", "launch.json"), `{
  "compounds": [{"name": "Run All Onyx Services", "configurations": ["Web Server", "API Server", "Celery primary"]}],
  "configurations": [
    {"name": "Web Server", "type": "node", "request": "launch", "cwd": "${workspaceRoot}/web", "runtimeExecutable": "bun", "runtimeArgs": ["run", "dev"]},
    {"name": "API Server", "type": "debugpy", "request": "launch", "module": "uvicorn", "cwd": "${workspaceFolder}/backend", "args": ["onyx.main:app", "--port", "8080"]},
    {"name": "Celery primary", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/backend/scripts/dev_celery_reload.py", "cwd": "${workspaceFolder}/backend", "args": ["-A", "primary"]}
  ]
}`)
	cmd := NewRootCommand()
	cmd.SetArgs([]string{"stack", "plan", "--profile", "minimal"})
	out := composeCapture(t, &os.Stdout, func() {
		if err := cmd.Execute(); err != nil {
			t.Error(err)
		}
	})
	python := devstack.PythonExecutable(root)
	want := "web (Web Server): cd " + filepath.Join(root, "web") + " && bun run dev\n" +
		"api (API Server): cd " + filepath.Join(root, "backend") + " && " + python + " -m uvicorn onyx.main:app --port 8080\n"
	if out != want {
		t.Errorf("plan output:\n%s\nwant:\n%s", out, want)
	}
}

func TestPrintStackStatus(t *testing.T) {
	healthy := true
	status := &devstack.Status{
		Project: "onyx-abc", Profile: "default", Phase: devstack.PhaseReady, Ready: true,
		Ports: map[string]int{"web": 3000, "api": 8080},
		URLs:  map[string]string{"web": "http://localhost:3000", "api": "http://localhost:8080"},
		Services: []devstack.ServiceStatus{
			{Name: "Web Server", Slug: "web", State: devstack.StateRunning, PID: 12, Healthy: &healthy},
			{Name: "Slack Bot", Slug: "slack-bot", State: devstack.StateSkipped, Reason: "port 8000 busy"},
		},
		Errors: []string{"boom"},
	}
	text := composeCapture(t, &os.Stdout, func() { printStackStatus(status, false) })
	for _, want := range []string{"project: onyx-abc", "ready:   true", "api:     http://localhost:8080", "running  web", "healthy", "skipped  slack-bot", "port 8000 busy", "error:   boom"} {
		if !strings.Contains(text, want) {
			t.Errorf("text status lacks %q:\n%s", want, text)
		}
	}
	js := composeCapture(t, &os.Stdout, func() { printStackStatus(status, true) })
	if !strings.Contains(js, `"phase": "ready"`) || !strings.Contains(js, `"healthy": true`) {
		t.Errorf("json status:\n%s", js)
	}
}

func TestRunStackLogs(t *testing.T) {
	root, calls := stackTestRepo(t)
	stack, _ := openStack()
	if err := runStackLogs(stack, nil, 10, false); err == nil || !strings.Contains(err.Error(), "no dev stack") {
		t.Errorf("logs without state: %v", err)
	}
	webLog := filepath.Join(root, "web.log")
	apiLog := filepath.Join(root, "api.log")
	st := &devstack.State{Phase: devstack.PhaseReady, Services: []devstack.ServiceRecord{
		{Name: "Web Server", Slug: "web", Log: webLog, StartedAt: time.Now()},
		{Name: "API Server", Slug: "api", Log: apiLog, StartedAt: time.Now()},
		{Name: "Slack Bot", Slug: "slack-bot", Skipped: "busy"},
	}}
	if err := stack.WriteState(st); err != nil {
		t.Fatal(err)
	}

	if err := runStackLogs(stack, nil, 10, false); err != nil {
		t.Fatal(err)
	}
	if err := runStackLogs(stack, []string{"api"}, 5, true); err != nil {
		t.Fatal(err)
	}
	if err := runStackLogs(stack, []string{"nope"}, 5, false); err == nil || !strings.Contains(err.Error(), "no logs for nope") {
		t.Errorf("unknown service: %v", err)
	}
	tail := devtoolCalls(t, calls["tail"])
	if len(tail) != 2 {
		t.Fatalf("tail calls %v", tail)
	}
	if !reflect.DeepEqual(tail[0].Args, []string{"-n", "10", webLog, apiLog}) {
		t.Errorf("all logs: %v", tail[0].Args)
	}
	if !reflect.DeepEqual(tail[1].Args, []string{"-n", "5", "-F", apiLog}) {
		t.Errorf("one log followed: %v", tail[1].Args)
	}
}

// runStackCommand runs "ods stack <args>" and returns its stdout.
func runStackCommand(t *testing.T, args ...string) string {
	t.Helper()
	cmd := NewRootCommand()
	cmd.SetArgs(append([]string{"stack"}, args...))
	return composeCapture(t, &os.Stdout, func() {
		if err := cmd.Execute(); err != nil {
			t.Error(err)
		}
	})
}

func TestStackCommands_lifecycleWithFakeService(t *testing.T) {
	root, _ := stackTestRepo(t)
	// The only service is a worker with no port, run by a fake interpreter
	// that just stays alive.
	writeFile(t, filepath.Join(root, ".venv", "bin", "python"), "#!/bin/sh\nexec /bin/sleep 300\n")
	if err := os.Chmod(filepath.Join(root, ".venv", "bin", "python"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(root, ".vscode", "launch.json"), `{
  "compounds": [{"name": "Run All Onyx Services", "configurations": ["Celery primary"]}],
  "configurations": [
    {"name": "Celery primary", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/backend/scripts/dev_celery_reload.py", "cwd": "${workspaceFolder}/backend", "args": ["-A", "primary"]}
  ]
}`)
	stack, _ := openStack()
	t.Cleanup(func() {
		_ = stack.Stop(context.Background(), devstack.Options{StopTimeout: 2 * time.Second, LockWait: 10 * time.Second})
	})

	runStackCommand(t, "stop")
	runStackCommand(t, "down")

	out := runStackCommand(t, "up", "--profile", "full", "--skip-prepare", "--timeout", "20s", "--json")
	if !strings.Contains(out, `"phase": "ready"`) || !strings.Contains(out, `"slug": "celery-primary"`) {
		t.Fatalf("up output:\n%s", out)
	}
	if !strings.Contains(devtoolReadFile(t, filepath.Join(root, ".vscode", ".env")), "POSTGRES_PORT=5555") {
		t.Error("infra port was not written to .vscode/.env")
	}
	out = runStackCommand(t, "status")
	if !strings.Contains(out, "ready:   true") || !strings.Contains(out, "running  celery-primary") {
		t.Errorf("status output:\n%s", out)
	}
	runStackCommand(t, "logs", "celery-primary")
	out = runStackCommand(t, "restart", "--profile", "full", "--skip-prepare", "--timeout", "20s")
	if !strings.Contains(out, "phase:   ready") {
		t.Errorf("restart output:\n%s", out)
	}
	runStackCommand(t, "stop")
	st, err := stack.ReadState()
	if err != nil || st == nil || st.Phase != devstack.PhaseStopped || len(st.Services) != 0 {
		t.Errorf("state after stop: %+v %v", st, err)
	}
	runStackCommand(t, "down")
}
