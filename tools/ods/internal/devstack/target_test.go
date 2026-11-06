//go:build !windows

package devstack

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestResolveTargetUsesSavedSharedSelection(t *testing.T) {
	owner, caller := sharedPair(t)
	owner.Project = "chosen-data"
	if err := owner.WriteState(&State{Ports: map[string]int{"api": 8181, "POSTGRES_HOST_PORT": 5544}}); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(filepath.Join(owner.StateDir, stateFileName))
	if err != nil {
		t.Fatal(err)
	}
	target, err := ResolveTarget(caller.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	if !target.Managed || target.Project != owner.Project || target.OwnerRoot != owner.Root || target.Root != caller.Root || target.StateDir != owner.StateDir || target.Mode != Shared || target.Ports["POSTGRES_HOST_PORT"] != 5544 {
		t.Fatalf("wrong shared target: %+v", target)
	}
	after, err := os.ReadFile(filepath.Join(owner.StateDir, stateFileName))
	if err != nil || !reflect.DeepEqual(before, after) {
		t.Fatalf("read-only resolution changed state: %v", err)
	}
	explicit, err := ResolveTarget(caller.Root, "OTHER-DATA", Shared)
	if err != nil {
		t.Fatal(err)
	}
	if explicit.Managed || explicit.Project != "other-data" || len(explicit.Ports) != 0 || explicit.OwnerRoot != "" {
		t.Fatalf("explicit project inherited another dataset: %+v", explicit)
	}
	isolated, err := Open(caller.Root, "other-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if err := isolated.WriteState(&State{Ports: map[string]int{"api": 8282}}); err != nil {
		t.Fatal(err)
	}
	explicit, err = ResolveTarget(caller.Root, "other-data", Shared)
	if err != nil || !explicit.Managed || explicit.Mode != Isolated || explicit.StateDir != isolated.StateDir || explicit.Ports["api"] != 8282 {
		t.Fatalf("explicit legacy project lost its owner: %+v %v", explicit, err)
	}
}

func TestResolveTargetUsesLegacyMetadataWithoutTakingOwnership(t *testing.T) {
	owner, caller := sharedPair(t)
	legacy, err := Open(owner.Root, "existing-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if err := legacy.WriteState(&State{Phase: PhaseReady, Services: []ServiceRecord{{Slug: "api", PID: 123}}, Ports: map[string]int{"api": 8181}}); err != nil {
		t.Fatal(err)
	}
	target, err := ResolveTarget(caller.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	if !target.Managed || target.Mode != Isolated || target.Project != legacy.Project || target.StateDir != legacy.StateDir || target.OwnerRoot != owner.Root || target.Ports["api"] != 8181 {
		t.Fatalf("wrong legacy owner: %+v", target)
	}
	if _, err := os.Stat(owner.StateDir); !os.IsNotExist(err) {
		t.Fatalf("resolution created shared state: %v", err)
	}
	other, err := Open(caller.Root, "other-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if err := other.WriteState(&State{}); err != nil {
		t.Fatal(err)
	}
	if _, err := ResolveTarget(caller.Root, "", Shared); err == nil || !strings.Contains(err.Error(), "several existing dev datasets") {
		t.Fatalf("expected ambiguous dataset error, got %v", err)
	}
	explicit, err := ResolveTarget(caller.Root, legacy.Project, Shared)
	if err != nil || explicit.StateDir != legacy.StateDir {
		t.Fatalf("explicit selection failed: %+v %v", explicit, err)
	}
	isolated, err := ResolveTarget(caller.Root, "", Isolated)
	if err != nil || isolated.Project != other.Project || isolated.StateDir != other.StateDir {
		t.Fatalf("isolated selection leaked: %+v %v", isolated, err)
	}
}

func TestResolveTargetFreshMatchesStackProject(t *testing.T) {
	stack := newTestStack(t, t.TempDir())
	shared, err := Open(stack.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	target, err := ResolveTarget(stack.Root, "", Shared)
	if err != nil || target.Project != shared.Project || target.Managed || len(target.Ports) != 0 {
		t.Fatalf("fresh commands disagree: %+v %v", target, err)
	}
	if _, err := os.Stat(shared.StateDir); !os.IsNotExist(err) {
		t.Fatalf("read-only resolution created state: %v", err)
	}
}

func TestResolveTargetRejectsImplicitProjectChangedDuringSelection(t *testing.T) {
	base := newTestStack(t, t.TempDir())
	writer, err := Open(base.Root, "old-data", Shared)
	if err != nil {
		t.Fatal(err)
	}
	if err := writer.WriteState(&State{Phase: PhaseStopped}); err != nil {
		t.Fatal(err)
	}
	selected, err := Open(base.Root, "", Shared)
	if err != nil {
		t.Fatal(err)
	}
	writer.Project = "new-data"
	if err := writer.WriteState(&State{Phase: PhaseStopped}); err != nil {
		t.Fatal(err)
	}
	if target, err := resolveOpenedTarget(selected, false); err == nil || !strings.Contains(err.Error(), "retry") {
		t.Fatalf("implicit selection followed stale project: %+v %v", target, err)
	}
	if target, err := resolveOpenedTarget(selected, true); err != nil || target.Project != "old-data" || target.Managed {
		t.Fatalf("explicit project selection was not retained: %+v %v", target, err)
	}
}

func TestResolveManagedDatabaseTargetFindsActualIsolatedOwner(t *testing.T) {
	shared, caller := sharedPair(t)
	shared.Project = "shared-data"
	if err := shared.WriteState(&State{Ports: map[string]int{"POSTGRES_HOST_PORT": 5544}}); err != nil {
		t.Fatal(err)
	}
	isolated, err := Open(shared.Root, "isolated-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if err := isolated.WriteState(&State{Phase: PhaseReady, Ports: map[string]int{"POSTGRES_HOST_PORT": 5544}}); err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	script := "#!/bin/sh\ncase \"$*\" in\n 'port shared-data-relational_db-1 5432') echo '0.0.0.0:5544';;\n 'port isolated-data-relational_db-1 5432') echo '0.0.0.0:5555';;\n *) exit 1;;\nesac\n"
	if err := os.WriteFile(filepath.Join(bin, "docker"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	target, found, err := ResolveManagedDatabaseTarget(caller.Root, 5555, nil)
	if err != nil || !found || target.Project != isolated.Project || target.StateDir != isolated.StateDir || target.Mode != Isolated || target.OwnerRoot != isolated.Root || target.Root != caller.Root || target.Ports["POSTGRES_HOST_PORT"] != 5555 {
		t.Fatalf("wrong managed database owner: %+v %v %v", target, found, err)
	}
	target, found, err = ResolveManagedDatabaseTarget(caller.Root, 5544, nil)
	if err != nil || !found || target.Project != shared.Project || target.Mode != Shared {
		t.Fatalf("stale isolated lease overrode actual mapping: %+v %v %v", target, found, err)
	}
	if _, found, err := ResolveManagedDatabaseTarget(caller.Root, 6666, nil); err != nil || found {
		t.Fatalf("unknown network endpoint became managed: %v %v", found, err)
	}
}

func TestResolveManagedDatabaseTargetUsesSavedPortsAndRejectsAmbiguity(t *testing.T) {
	shared, caller := sharedPair(t)
	shared.Project = "shared-data"
	if err := shared.WriteState(&State{Ports: map[string]int{"POSTGRES_HOST_PORT": 5544}}); err != nil {
		t.Fatal(err)
	}
	isolated, err := Open(shared.Root, "isolated-data", Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if err := isolated.WriteState(&State{Phase: PhaseStopped, Ports: map[string]int{"POSTGRES_HOST_PORT": 5555}}); err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	if err := os.WriteFile(filepath.Join(bin, "docker"), []byte("#!/bin/sh\nexit 1\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	if target, found, err := ResolveManagedDatabaseTarget(caller.Root, 5555, nil); err != nil || !found || target.Project != isolated.Project {
		t.Fatalf("lost saved database claim: %+v %v %v", target, found, err)
	}
	if err := isolated.WriteState(&State{Ports: map[string]int{"POSTGRES_HOST_PORT": 5544}}); err != nil {
		t.Fatal(err)
	}
	if _, _, err := ResolveManagedDatabaseTarget(caller.Root, 5544, nil); err == nil || !strings.Contains(err.Error(), "several managed owners") {
		t.Fatalf("ambiguous database claim was accepted: %v", err)
	}
}

func TestResolveManagedDatabaseTargetFindsDurableOwnerInAnotherRepository(t *testing.T) {
	registry := t.TempDir()
	owner := newTestStack(t, registry)
	caller := newTestStack(t, registry)
	if err := owner.WriteState(&State{Phase: PhaseReady, Ports: map[string]int{"POSTGRES_HOST_PORT": 5555}}); err != nil {
		t.Fatal(err)
	}
	release, err := owner.LockInfrastructure(context.Background(), testOptions().LockWait)
	if err != nil {
		t.Fatal(err)
	}
	release()
	bin := t.TempDir()
	if err := os.WriteFile(filepath.Join(bin, "docker"), []byte("#!/bin/sh\nexit 1\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	target, found, err := ResolveManagedDatabaseTarget(caller.Root, 5555, owner.Registry)
	if err != nil || !found || target.Project != owner.Project || target.StateDir != owner.StateDir || target.OwnerRoot != owner.Root || target.Root != caller.Root {
		t.Fatalf("lost cross-repository database owner: %+v %v %v", target, found, err)
	}
	if _, found, err := ResolveManagedDatabaseTarget(owner.Root, 5555, owner.Registry); err != nil || !found {
		t.Fatalf("duplicate family/global claim became ambiguous: %v %v", found, err)
	}
	if err := owner.WriteState(&State{Phase: PhaseStopped, Ports: map[string]int{"POSTGRES_HOST_PORT": 5555}}); err != nil {
		t.Fatal(err)
	}
	adopter, err := Open(caller.Root, owner.Project, Shared)
	if err != nil {
		t.Fatal(err)
	}
	adopter.Registry = owner.Registry
	if err := adopter.WriteState(&State{Phase: PhaseReady, Ports: map[string]int{"POSTGRES_HOST_PORT": 5555}}); err != nil {
		t.Fatal(err)
	}
	release, err = adopter.LockInfrastructure(context.Background(), testOptions().LockWait)
	if err != nil {
		t.Fatal(err)
	}
	release()
	if target, found, err := ResolveManagedDatabaseTarget(owner.Root, 5555, owner.Registry); err != nil || !found || target.StateDir != adopter.StateDir || target.OwnerRoot != adopter.Root {
		t.Fatalf("stale family metadata overrode global owner: %+v %v %v", target, found, err)
	}
	path := filepath.Join(registry, "projects", ProjectName(owner.Project), "owner.json")
	if err := os.WriteFile(path, []byte("broken owner record"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := ResolveManagedDatabaseTarget(caller.Root, 5555, owner.Registry); err == nil || !strings.Contains(err.Error(), "parse project owner") {
		t.Fatalf("corrupt owner claim was ignored: %v", err)
	}
}

func TestTargetEnvironmentUsesRecordedPortsAndOrdinaryShellValues(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".vscode"), 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, ".vscode", ".env")
	file := []byte("POSTGRES_PASSWORD=file-password\nORDINARY_SETTING=file-value\nPOSTGRES_HOST=old-db\nPOSTGRES_PORT=1111\n")
	if err := os.WriteFile(path, file, 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("POSTGRES_PASSWORD", "shell-password")
	t.Setenv("ORDINARY_SETTING", "shell-value")
	t.Setenv("POSTGRES_HOST", "stale-shell-db")
	target := Target{Root: root, Project: "chosen-data", Ports: map[string]int{
		"POSTGRES_HOST_PORT": 5544, "REDIS_HOST_PORT": 6388, "OPENSEARCH_HOST_PORT": 9222,
		"MODEL_SERVER_HOST_PORT": 9009, "OBJECT_STORE_HOST_PORT": 9011, "CODE_INTERPRETER_HOST_PORT": 8011,
		"api": 8181, "web": 3111, "mcp": 8191,
	}}
	t.Setenv("PATH", t.TempDir())
	env, err := target.Environment()
	if err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]string{
		"POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5544", "POSTGRES_PASSWORD": "shell-password", "ORDINARY_SETTING": "shell-value",
		"REDIS_HOST": "localhost", "REDIS_PORT": "6388", "OPENSEARCH_REST_API_PORT": "9222",
		"S3_ENDPOINT_URL": "http://localhost:9011", "INTERNAL_URL": "http://localhost:8181", "WEB_DOMAIN": "http://localhost:3111",
		"CODE_INTERPRETER_BASE_URL": "http://localhost:8011", "MCP_INTERNAL_URL": "http://localhost:8191",
	} {
		if got := EnvValue(env, key); got != want {
			t.Errorf("%s: got %q, want %q", key, got, want)
		}
	}
	after, err := os.ReadFile(path)
	if err != nil || !reflect.DeepEqual(file, after) {
		t.Fatalf("environment resolution wrote file: %v", err)
	}
	serviceEnv, err := target.ServiceEnv()
	if err != nil {
		t.Fatal(err)
	}
	launchEnv := serviceEnv.With([]string{"ORDINARY_SETTING=launch-value", "POSTGRES_PASSWORD=launch-password", "POSTGRES_PORT=9999", "INTERNAL_URL=http://stale:9999"})
	if got := EnvValue(launchEnv, "INTERNAL_URL"); got != "http://localhost:8181" {
		t.Fatalf("launch environment overrode endpoint: %s", got)
	}
	if got := EnvValue(launchEnv, "ORDINARY_SETTING"); got != "shell-value" {
		t.Fatalf("launch environment overrode shell value: %s", got)
	}
	if got := EnvValue(launchEnv, "POSTGRES_PASSWORD"); got != "shell-password" {
		t.Fatal("launch environment overrode shell credentials")
	}
	if got := EnvValue(launchEnv, "POSTGRES_PORT"); got != "5544" {
		t.Fatalf("launch environment overrode database binding: %s", got)
	}
}

func TestTargetEnvironmentDiscoversOnlyExactProjectPorts(t *testing.T) {
	bin := t.TempDir()
	log := filepath.Join(t.TempDir(), "calls")
	t.Setenv("ODS_TARGET_CALLS", log)
	script := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$ODS_TARGET_CALLS\"\ncase \"$*\" in\n  'port chosen-data-relational_db-1 5432') echo '0.0.0.0:5544';;\n  'port chosen-data-cache-1 6379') echo '127.0.0.1:6388';;\n  *) exit 1;;\nesac\n"
	if err := os.WriteFile(filepath.Join(bin, "docker"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin)
	target := Target{Root: t.TempDir(), Project: "chosen-data", Ports: map[string]int{}}
	env, err := target.Environment()
	if err != nil {
		t.Fatal(err)
	}
	if EnvValue(env, "POSTGRES_PORT") != "5544" || EnvValue(env, "REDIS_PORT") != "6388" {
		t.Fatalf("actual port mapping ignored")
	}
	calls, err := os.ReadFile(log)
	if err != nil {
		t.Fatal(err)
	}
	for _, call := range strings.Split(strings.TrimSpace(string(calls)), "\n") {
		if !strings.HasPrefix(call, "port chosen-data-") {
			t.Fatalf("looked outside target project: %s", call)
		}
	}
	if len(target.Ports) != 0 {
		t.Fatalf("discovery mutated recorded target ports: %+v", target.Ports)
	}
}

func TestHostServiceEnvDoesNotDiscoverPortsAndLocalModelWins(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	t.Setenv("MODEL_SERVER_HOST", "stale-host")
	t.Setenv("INDEXING_MODEL_SERVER_HOST", "stale-index-host")
	env := HostServiceEnv(map[string]int{"MODEL_SERVER_HOST_PORT": 9009, "model": 9019})
	for _, key := range []string{"MODEL_SERVER_PORT", "INDEXING_MODEL_SERVER_PORT"} {
		if got := EnvValue(env.With([]string{key + "=9999"}), key); got != "9019" {
			t.Errorf("%s: got %q, want local model port", key, got)
		}
	}
	for _, key := range []string{"MODEL_SERVER_HOST", "INDEXING_MODEL_SERVER_HOST"} {
		if got := EnvValue(env.With(), key); got != "localhost" {
			t.Errorf("%s: got %q, want localhost", key, got)
		}
	}
}

func TestHostServiceEnvDoesNotLoadBackendSecretsIntoWeb(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".vscode"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".vscode", ".env"), []byte("ODS_BACKEND_PRIVATE_KEY=backend-only\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".vscode", ".env.web"), []byte("ODS_WEB_SETTING=web-value\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	launch := &Launch{Configurations: []LaunchConfig{{Name: "Web Server", Type: "node", Request: "launch", RuntimeExecutable: "bun", EnvFile: "${workspaceFolder}/.vscode/.env.web"}}}
	ports := map[string]int{"web": 3111, "api": 8181}
	spec, err := Translate(root, launch.Configurations[0], ports, HostServiceEnv(ports))
	if err != nil {
		t.Fatal(err)
	}
	if EnvValue(spec.Env, "ODS_BACKEND_PRIVATE_KEY") != "" {
		t.Fatal("web service received backend-only file secret")
	}
	if EnvValue(spec.Env, "ODS_WEB_SETTING") != "web-value" {
		t.Fatal("web service did not load its own configuration")
	}
}
