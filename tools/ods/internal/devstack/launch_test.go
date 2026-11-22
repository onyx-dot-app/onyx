package devstack

import (
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestStripJSONC(t *testing.T) {
	cases := []struct{ name, in, want string }{
		{"line comment", "{\n // c\n \"a\": 1 // d\n}", "{\n \n \"a\": 1 \n}"},
		{"block comment", `{"a": /* x */ 1}`, `{"a":  1}`},
		{"trailing commas", "{\"a\": [1, 2,], \n}", "{\"a\": [1, 2] \n}"},
		{"comma inside string kept", `{"a": "x,]", "b": "//not a comment"}`, `{"a": "x,]", "b": "//not a comment"}`},
		{"escaped quote in string", `{"a": "q\"//", "b": 1,}`, `{"a": "q\"//", "b": 1}`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := string(StripJSONC([]byte(c.in)))
			if got != c.want {
				t.Errorf("got %q, want %q", got, c.want)
			}
			if !json.Valid([]byte(got)) {
				t.Errorf("result is not valid JSON: %q", got)
			}
		})
	}
}

const testLaunch = `{
  // comments and trailing commas are allowed
  "compounds": [
    {"name": "Run All Onyx Services", "configurations": ["Web Server", "Model Server", "API Server", "MCP Server", "Slack Bot", "Celery primary", "Celery heavy",],},
  ],
  "configurations": [
    {"name": "Web Server", "type": "node", "request": "launch", "cwd": "${workspaceRoot}/web", "runtimeExecutable": "bun", "envFile": "${workspaceFolder}/.vscode/.env.web", "runtimeArgs": ["run", "dev"]},
    {"name": "Model Server", "type": "debugpy", "request": "launch", "module": "uvicorn", "cwd": "${workspaceFolder}/backend", "envFile": "${workspaceFolder}/.vscode/.env", "args": ["model_server.main:app", "--port", "9000"]},
    {"name": "API Server", "type": "debugpy", "request": "launch", "module": "uvicorn", "cwd": "${workspaceFolder}/backend", "envFile": "${workspaceFolder}/.vscode/.env", "env": {"LOG_LEVEL": "DEBUG"}, "args": ["onyx.main:app", "--reload-exclude", "${workspaceFolder}/backend/x", "--port", "8080"]},
    {"name": "MCP Server", "type": "debugpy", "request": "launch", "module": "uvicorn", "cwd": "${workspaceFolder}/backend", "env": {"MCP_SERVER_PORT": "8090"}, "args": ["onyx.mcp_server.api:mcp_app", "--port", "8090"]},
    {"name": "Slack Bot", "type": "debugpy", "request": "launch", "program": "onyx/onyxbot/slack/listener.py", "cwd": "${workspaceFolder}/backend", "env": {"PYTHONPATH": "."}},
    {"name": "Celery primary", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/backend/scripts/dev_celery_reload.py", "cwd": "${workspaceFolder}/backend", "args": ["-A", "primary", "worker", "-Q", "celery"]},
    {"name": "Celery heavy", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/backend/scripts/dev_celery_reload.py", "cwd": "${workspaceFolder}/backend", "args": ["-A", "heavy", "worker"]},
  ]
}`

func writeLaunchFixture(t *testing.T) (root string, launch *Launch) {
	t.Helper()
	root = t.TempDir()
	vscode := filepath.Join(root, ".vscode")
	if err := os.MkdirAll(vscode, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(vscode, "launch.json")
	if err := os.WriteFile(path, []byte(testLaunch), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(vscode, ".env"), []byte("SECRET=from-env\nPOSTGRES_HOST=relational_db\nLOG_LEVEL=INFO\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(vscode, ".env.web"), []byte("AUTH_TYPE=basic\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	launch, err := LoadLaunch(path)
	if err != nil {
		t.Fatal(err)
	}
	return root, launch
}

func slugs(specs []Spec) []string {
	var out []string
	for _, sp := range specs {
		out = append(out, sp.Slug)
	}
	return out
}

func TestLaunchPlan_profiles(t *testing.T) {
	root, launch := writeLaunchFixture(t)
	ports := map[string]int{"web": 3100, "api": 8180, "mcp": 8190, "model": 9100}
	env := Env{Base: []string{"HOME=/h"}, Overrides: []string{"POSTGRES_HOST=localhost", "MCP_SERVER_PORT=8190", "PORT=3100"}}

	cases := []struct {
		opts Options
		want []string
	}{
		{Options{Profile: ProfileMinimal}, []string{"web", "api"}},
		{Options{Profile: ProfileDefault}, []string{"web", "api", "celery-primary"}},
		{Options{Profile: ProfileFull}, []string{"web", "api", "mcp", "slack-bot", "celery-primary", "celery-heavy"}},
		{Options{Profile: ProfileFull, LocalModelServer: true}, []string{"web", "model", "api", "mcp", "slack-bot", "celery-primary", "celery-heavy"}},
		{Options{Profile: ProfileMinimal, LocalModelServer: true}, []string{"web", "model", "api"}},
	}
	for _, c := range cases {
		specs, err := LaunchPlan(root, launch, ports, env, c.opts)
		if err != nil {
			t.Fatalf("%+v: %v", c.opts, err)
		}
		if got := slugs(specs); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%+v: got %v, want %v", c.opts, got, c.want)
		}
	}
	if _, err := LaunchPlan(root, launch, ports, env, Options{Profile: "nope"}); err == nil {
		t.Error("unknown profile accepted")
	}
}

func TestResolveServiceUsesLaunchConfiguration(t *testing.T) {
	root, launch := writeLaunchFixture(t)
	sp, err := ResolveService(root, launch, "api", map[string]int{"api": 8181}, Env{})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{PythonExecutable(root), "-m", "uvicorn", "onyx.main:app", "--reload-exclude", filepath.Join(root, "backend", "x"), "--port", "8181"}
	if !reflect.DeepEqual(sp.Command, want) || sp.Dir != filepath.Join(root, "backend") || EnvValue(sp.Env, "LOG_LEVEL") != "DEBUG" {
		t.Fatalf("resolved service = %+v", sp)
	}
	if _, err := ResolveService(root, launch, "missing", nil, Env{}); err == nil || !strings.Contains(err.Error(), `no service "missing"`) {
		t.Fatalf("missing service error = %v", err)
	}
}

func TestTranslate_portsAndEnv(t *testing.T) {
	root, launch := writeLaunchFixture(t)
	ports := map[string]int{"web": 3100, "api": 8180, "mcp": 8190, "model": 9100}
	env := Env{Base: []string{"HOME=/h", "LOG_LEVEL=WARNING"}, Overrides: []string{"POSTGRES_HOST=localhost", "MCP_SERVER_PORT=8190", "PORT=3100", "INTERNAL_URL=http://localhost:8180"}}
	specs, err := LaunchPlan(root, launch, ports, env, Options{Profile: ProfileFull, LocalModelServer: true})
	if err != nil {
		t.Fatal(err)
	}
	bySlug := map[string]Spec{}
	for _, sp := range specs {
		bySlug[sp.Slug] = sp
	}
	python := PythonExecutable(root)

	api := bySlug["api"]
	wantAPI := []string{python, "-m", "uvicorn", "onyx.main:app", "--reload-exclude", filepath.Join(root, "backend", "x"), "--port", "8180"}
	if !reflect.DeepEqual(api.Command, wantAPI) {
		t.Errorf("api command %v, want %v", api.Command, wantAPI)
	}
	if api.Dir != filepath.Join(root, "backend") || api.Port != 8180 || api.Health != "http://localhost:8180/health" {
		t.Errorf("api spec %+v", api)
	}
	// Layering: shell < envFile < launch env < overrides.
	for key, want := range map[string]string{"HOME": "/h", "SECRET": "from-env", "LOG_LEVEL": "DEBUG", "POSTGRES_HOST": "localhost"} {
		if got := EnvValue(api.Env, key); got != want {
			t.Errorf("api env %s=%q, want %q", key, got, want)
		}
	}

	mcp := bySlug["mcp"]
	if got := EnvValue(mcp.Env, "MCP_SERVER_PORT"); got != "8190" {
		t.Errorf("mcp MCP_SERVER_PORT=%q", got)
	}
	if mcp.Command[len(mcp.Command)-1] != "8190" {
		t.Errorf("mcp command %v", mcp.Command)
	}
	if got := EnvValue(mcp.Env, "SECRET"); got != "" {
		t.Errorf("mcp without envFile got SECRET=%q", got)
	}

	web := bySlug["web"]
	if !reflect.DeepEqual(web.Command, []string{"bun", "run", "dev"}) || web.Dir != filepath.Join(root, "web") {
		t.Errorf("web spec %+v", web)
	}
	if EnvValue(web.Env, "AUTH_TYPE") != "basic" || EnvValue(web.Env, "PORT") != "3100" || EnvValue(web.Env, "SECRET") != "" {
		t.Errorf("web env wrong: %v", web.Env)
	}

	model := bySlug["model"]
	if model.Command[len(model.Command)-1] != "9100" || model.Port != 9100 {
		t.Errorf("model spec %+v", model)
	}
	slack := bySlug["slack-bot"]
	if !slack.Optional || !reflect.DeepEqual(slack.Command, []string{python, "onyx/onyxbot/slack/listener.py"}) {
		t.Errorf("slack spec %+v", slack)
	}
	worker := bySlug["celery-primary"]
	if worker.Command[1] != filepath.Join(root, "backend", "scripts", "dev_celery_reload.py") || worker.Port != 0 {
		t.Errorf("worker spec %+v", worker)
	}

	// The spec hash does not change with env order.
	shuffled := api
	shuffled.Env = append([]string{api.Env[len(api.Env)-1]}, api.Env[:len(api.Env)-1]...)
	if shuffled.Hash() != api.Hash() {
		t.Error("hash depends on env order")
	}
}

func TestPrepareEnvFiles(t *testing.T) {
	root := t.TempDir()
	vscode := filepath.Join(root, ".vscode")
	if err := os.MkdirAll(vscode, 0o755); err != nil {
		t.Fatal(err)
	}
	template := "GEN_AI_API_KEY=<REPLACE THIS>\nLANGSMITH_API_KEY=<REPLACE_THIS>\nLANGSMITH_TRACING=\"true\"\nSAML_CONF_DIR=/<ABSOLUTE PATH TO ONYX>/onyx/backend/ee/onyx/configs/saml_config\nKEEP=1\n"
	if err := os.WriteFile(filepath.Join(vscode, "env_template.txt"), []byte(template), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(vscode, "env.web_template.txt"), []byte("AUTH_TYPE=basic\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	// .env.web is a symlink into another checkout.
	other := filepath.Join(t.TempDir(), ".env.web")
	if err := os.WriteFile(other, []byte("SHARED_SECRET=abc\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(other, filepath.Join(vscode, ".env.web")); err != nil {
		t.Fatal(err)
	}

	created, localized, err := PrepareEnvFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(created, []string{filepath.Join(vscode, ".env")}) {
		t.Errorf("created %v", created)
	}
	if !reflect.DeepEqual(localized, []string{filepath.Join(vscode, ".env.web")}) {
		t.Errorf("localized %v", localized)
	}
	env, err := os.ReadFile(filepath.Join(vscode, ".env"))
	if err != nil {
		t.Fatal(err)
	}
	want := "GEN_AI_API_KEY=\nLANGSMITH_API_KEY=\nLANGSMITH_TRACING=false\nSAML_CONF_DIR=" + filepath.Join(root, "backend", "ee", "onyx", "configs", "saml_config") + "\nKEEP=1\n"
	if string(env) != want {
		t.Errorf("env:\n%s\nwant:\n%s", env, want)
	}
	info, err := os.Lstat(filepath.Join(vscode, ".env.web"))
	if err != nil || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm() != 0o600 {
		t.Errorf(".env.web is not a private regular file: %v %v", info, err)
	}
	web, _ := os.ReadFile(filepath.Join(vscode, ".env.web"))
	if string(web) != "SHARED_SECRET=abc\n" {
		t.Errorf(".env.web content %q", web)
	}
	if src, _ := os.ReadFile(other); string(src) != "SHARED_SECRET=abc\n" {
		t.Error("symlink target was modified")
	}

	// A second run changes nothing.
	created, localized, err = PrepareEnvFiles(root)
	if err != nil || created != nil || localized != nil {
		t.Errorf("second run: %v %v %v", created, localized, err)
	}
}

func TestProjectName(t *testing.T) {
	a := ProjectName("/w/onyx")
	b := ProjectName("/other/onyx")
	if a == b {
		t.Errorf("same project for different paths: %s", a)
	}
	if !strings.HasPrefix(a, "onyx-") || len(a) != len("onyx-")+8 {
		t.Errorf("project %q", a)
	}
	if got := ProjectName("/w/My Feature!"); !strings.HasPrefix(got, "myfeature-") {
		t.Errorf("project %q", got)
	}
}

func TestRegistry_leasesAreDurableAndDisjoint(t *testing.T) {
	r := &Registry{Dir: t.TempDir()}
	rootA, rootB := t.TempDir(), t.TempDir()
	base := freeBasePort()
	reqs := []PortRequest{{Name: "web", Preferred: base}, {Name: "api", Preferred: base}}

	a, err := r.LeaseFor(rootA, "", reqs)
	if err != nil {
		t.Fatal(err)
	}
	if a["web"] == a["api"] {
		t.Errorf("same port for two names: %v", a)
	}
	b, err := r.LeaseFor(rootB, "", reqs)
	if err != nil {
		t.Fatal(err)
	}
	if b["web"] == a["web"] || b["web"] == a["api"] || b["api"] == a["web"] {
		t.Errorf("leases overlap: %v %v", a, b)
	}
	again, err := r.LeaseFor(rootA, "", reqs)
	if err != nil || !reflect.DeepEqual(again, a) {
		t.Errorf("lease not durable: %v %v", again, err)
	}
	// A fixed port is recorded as is, and 8000 is never leased.
	fixed, err := r.LeaseFor(rootA, "", []PortRequest{{Name: "db", Fixed: 5555}, {Name: "ci", Preferred: 8000}})
	if err != nil || fixed["db"] != 5555 || fixed["ci"] == 8000 {
		t.Errorf("fixed/never lease: %v %v", fixed, err)
	}
	// Leases of a removed worktree are reclaimed.
	if err := os.RemoveAll(rootB); err != nil {
		t.Fatal(err)
	}
	if _, err := r.LeaseFor(rootA, "", nil); err != nil {
		t.Fatal(err)
	}
	leases, _ := r.Leases()
	for _, l := range leases {
		if l.Root == rootB {
			t.Errorf("stale lease kept: %+v", l)
		}
	}
}

// freeBasePort returns a port region away from the ports a live dev stack
// uses.
func freeBasePort() int {
	ln, err := net.Listen("tcp", ":0")
	if err != nil {
		return 42000
	}
	defer func() { _ = ln.Close() }()
	return 30000 + ln.Addr().(*net.TCPAddr).Port%20000
}
