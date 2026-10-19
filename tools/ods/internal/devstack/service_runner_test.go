//go:build !windows

package devstack

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

func serviceRunnerDatabase(t *testing.T, project string, port int) {
	t.Helper()
	bin := t.TempDir()
	t.Setenv("ODS_TEST_DB_CONTAINER", docker.ContainerName(project, "relational_db"))
	t.Setenv("ODS_TEST_DB_PORT", fmt.Sprint(port))
	script := "#!/bin/sh\n[ \"$1\" = port ] && [ \"$2\" = \"$ODS_TEST_DB_CONTAINER\" ] && [ \"$3\" = 5432 ] || exit 1\nprintf '0.0.0.0:%s\\n' \"$ODS_TEST_DB_PORT\"\n"
	if err := os.WriteFile(filepath.Join(bin, "docker"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func TestRunServicePreservesForeignSharedOwner(t *testing.T) {
	for _, stale := range []bool{false, true} {
		t.Run(fmt.Sprintf("stale-record=%v", stale), func(t *testing.T) {
			owner, caller := sharedPair(t)
			mustUp(t, owner, &fakeProvider{services: []string{"api"}})
			api := servicePID(t, owner, "api")
			state, err := owner.ReadState()
			if err != nil {
				t.Fatal(err)
			}
			if stale {
				state.Services[0].StartMarker = "stale-record"
				if err := owner.WriteState(state); err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() {
					state.Services[0].StartMarker = api.StartMarker
					if err := owner.WriteState(state); err != nil {
						t.Error(err)
					}
				})
			}
			path := filepath.Join(owner.StateDir, stateFileName)
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			target, err := ResolveTarget(caller.Root, "", Shared)
			if err != nil {
				t.Fatal(err)
			}
			err = caller.RunService(context.Background(), target, &Launch{}, "api", ServiceOptions{})
			if err == nil || !strings.Contains(err.Error(), owner.Root) {
				t.Fatalf("foreign-owner startup error=%v", err)
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) || !isCurrent(api) {
				t.Fatalf("foreign startup changed owner state or stopped its API: %v", err)
			}
		})
	}
}

func TestServiceLauncherPreservesForegroundIOAndExitStatus(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "service.log")
	var stdout, stderr bytes.Buffer
	sp := Spec{
		Name: "API Server", Slug: "api", Dir: t.TempDir(), Env: os.Environ(),
		Command: []string{"/bin/sh", "-c", "read line; printf 'out:%s' \"$line\"; printf 'err:%s' \"$1\" >&2; exit 7", "service", "two words"},
	}
	record, done, err := launchService(sp, logPath, ServiceIO{Stdin: strings.NewReader("input\n"), Stdout: &stdout, Stderr: &stderr})
	if err != nil {
		t.Fatal(err)
	}
	err = <-done
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 7 {
		t.Fatalf("exit error = %v, want exit status 7", err)
	}
	if stdout.String() != "out:input" || stderr.String() != "err:two words" {
		t.Fatalf("stdout=%q stderr=%q", stdout.String(), stderr.String())
	}
	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "out:input") || !strings.Contains(string(data), "err:two words") || record.Log != logPath || record.Slug != "api" {
		t.Fatalf("record=%+v log=%q", record, data)
	}
}

func TestServicePortCanReplaceAnOldLease(t *testing.T) {
	registry := &Registry{Dir: t.TempDir()}
	root := t.TempDir()
	first, err := registry.Lease(root, []PortRequest{{Name: "api", Preferred: testBasePort + 200}})
	if err != nil {
		t.Fatal(err)
	}
	second, err := registry.Lease(root, []PortRequest{{Name: "api", Preferred: testBasePort + 201, Replace: true}})
	if err != nil || first["api"] != testBasePort+200 || second["api"] != testBasePort+201 {
		t.Fatalf("first=%v second=%v err=%v", first, second, err)
	}
	listener, err := net.Listen("tcp", fmt.Sprintf(":%d", testBasePort+202))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = listener.Close() }()
	third, err := registry.Lease(root, []PortRequest{{Name: "api", Preferred: testBasePort + 202, Replace: true}})
	if err != nil || third["api"] != testBasePort+203 {
		t.Fatalf("replacement for busy port=%v err=%v", third, err)
	}
}

func TestRunServiceUsesOnlyARunningLocalModel(t *testing.T) {
	for _, scenario := range []string{"stopped model", "running model", "starting model"} {
		t.Run(scenario, func(t *testing.T) {
			s := newTestStack(t, t.TempDir())
			serviceRunnerDatabase(t, s.Project, testBasePort+500)
			modelPort := testBasePort + 550
			if scenario == "running model" {
				mustUp(t, s, &fakeProvider{services: []string{"model"}})
				modelPort = servicePID(t, s, "model").Port
			} else if err := s.WriteState(&State{Phase: PhaseStopped, Ports: map[string]int{"model": modelPort}, Services: []ServiceRecord{{Slug: "model", Port: modelPort}}}); err != nil {
				t.Fatal(err)
			}
			target := Target{Root: s.Root, OwnerRoot: s.Root, Project: s.Project, StateDir: s.StateDir, Mode: s.Mode, Ports: map[string]int{}}
			for _, service := range docker.InfraServices {
				for _, port := range service.Ports {
					target.Ports[port.ComposeVar] = testBasePort + 500
				}
			}
			slug, name := "api", "API Server"
			wantPort := testBasePort + 500
			switch scenario {
			case "running model":
				wantPort = modelPort
			case "starting model":
				slug, name, wantPort = "model", "Model Server", testBasePort+200
			}
			launch := &Launch{Configurations: []LaunchConfig{{
				Name: name, Type: "node", Request: "launch", Cwd: s.Root,
				RuntimeExecutable: "/bin/sh", RuntimeArgs: []string{"-c", "printf '%s' \"$MODEL_SERVER_PORT\""},
			}}}
			var output bytes.Buffer
			if err := s.RunService(context.Background(), target, launch, slug, ServiceOptions{PreferredPort: testBasePort + 200, IO: ServiceIO{Stdout: &output}}); err != nil {
				t.Fatal(err)
			}
			if got, want := output.String(), fmt.Sprint(wantPort); got != want {
				t.Fatalf("model server port=%q, want %q", got, want)
			}
			state, err := s.ReadState()
			if err != nil {
				t.Fatal(err)
			}
			if scenario != "starting model" && state.Ports["model"] != modelPort {
				t.Fatalf("durable local model port changed: %+v", state.Ports)
			}
		})
	}
}

func TestFrontendUsesTheBackendModelProcessState(t *testing.T) {
	source := newTestStack(t, t.TempDir())
	mustUp(t, source, &fakeProvider{services: []string{"api", "model"}})
	api, model := servicePID(t, source, "api"), servicePID(t, source, "model")
	state, err := source.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	target := Target{Root: source.Root, OwnerRoot: source.Root, Project: source.Project, StateDir: source.StateDir, Mode: source.Mode, Ports: state.Ports}
	for _, service := range docker.InfraServices {
		for _, port := range service.Ports {
			target.Ports[port.ComposeVar] = testBasePort + 500
		}
	}
	preview, err := Open(source.Root, source.Project, Frontend)
	if err != nil {
		t.Fatal(err)
	}
	preview.Registry = source.Registry
	launch := &Launch{Configurations: []LaunchConfig{{
		Name: "Web Server", Type: "node", Request: "launch", Cwd: source.Root,
		RuntimeExecutable: "/bin/sh", RuntimeArgs: []string{"-c", "printf '%s' \"$MODEL_SERVER_PORT\""},
	}}}
	for _, modelRunning := range []bool{true, false} {
		wantPort := model.Port
		if !modelRunning {
			if left := stopRecords([]ServiceRecord{model}, time.Second); len(left) > 0 {
				t.Fatalf("model did not stop: %+v", left)
			}
			wantPort = testBasePort + 500
		}
		var output bytes.Buffer
		if err := preview.RunService(context.Background(), target, launch, "web", ServiceOptions{PreferredPort: testBasePort + 300, IO: ServiceIO{Stdout: &output}}); err != nil {
			t.Fatal(err)
		}
		if got, want := output.String(), fmt.Sprint(wantPort); got != want {
			t.Fatalf("modelRunning=%v web model port=%q, want %q", modelRunning, got, want)
		}
		if !isCurrent(api) {
			t.Fatal("web preview stopped its API")
		}
	}
	state, err = source.ReadState()
	if err != nil || state.Ports["model"] != model.Port {
		t.Fatalf("backend model lease changed: state=%+v err=%v", state, err)
	}
}

func TestFrontendCanChangeProjectsOnlyAfterItsProcessStops(t *testing.T) {
	for _, running := range []bool{false, true} {
		t.Run(fmt.Sprintf("running=%v", running), func(t *testing.T) {
			registry := t.TempDir()
			oldSource := newTestStack(t, registry)
			newSource := newTestStack(t, registry)
			mustUp(t, oldSource, &fakeProvider{services: []string{"api"}})
			mustUp(t, newSource, &fakeProvider{services: []string{"api"}})
			targetFor := func(source *Stack) Target {
				return Target{Root: source.Root, OwnerRoot: source.Root, Project: source.Project, StateDir: source.StateDir, Mode: source.Mode, Ports: map[string]int{"api": servicePID(t, source, "api").Port}}
			}
			preview, err := Open(oldSource.Root, oldSource.Project, Frontend)
			if err != nil {
				t.Fatal(err)
			}
			preview.Registry = oldSource.Registry
			launch := &Launch{Configurations: []LaunchConfig{{
				Name: "Web Server", Type: "node", Request: "launch", Cwd: preview.Root,
				RuntimeExecutable: "/bin/sh", RuntimeArgs: []string{"-c", "printf 'preview:%s' \"$INTERNAL_URL\""},
			}}}
			var output bytes.Buffer
			if err := preview.RunService(context.Background(), targetFor(oldSource), launch, "web", ServiceOptions{IO: ServiceIO{Stdout: &output}}); err != nil {
				t.Fatal(err)
			}
			if output.String() != fmt.Sprintf("preview:http://localhost:%d", servicePID(t, oldSource, "api").Port) {
				t.Fatalf("old preview output=%q", output.String())
			}
			var active ServiceRecord
			if running {
				port := freeBasePort()
				specs, err := (&fakeProvider{services: []string{"web"}}).Plan(preview.Root, map[string]int{"web": port}, Env{}, testOptions())
				if err != nil {
					t.Fatal(err)
				}
				active, err = startService(specs[0], filepath.Join(preview.LogDir(), "web.log"))
				if err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() { _ = stopRecords([]ServiceRecord{active}, time.Second) })
				if err := preview.WriteState(&State{Phase: PhaseReady, Services: []ServiceRecord{active}}); err != nil {
					t.Fatal(err)
				}
			}
			next, err := Open(preview.Root, newSource.Project, Frontend)
			if err != nil {
				t.Fatal(err)
			}
			next.Registry = preview.Registry
			output.Reset()
			err = next.RunService(context.Background(), targetFor(newSource), launch, "web", ServiceOptions{IO: ServiceIO{Stdout: &output}})
			if running {
				if err == nil || !strings.Contains(err.Error(), "frontend already uses project "+oldSource.Project) || !isCurrent(active) {
					t.Fatalf("active preview switch error=%v process=%+v", err, active)
				}
				return
			}
			if err != nil {
				t.Fatalf("switch stopped preview to new project: %v", err)
			}
			if output.String() != fmt.Sprintf("preview:http://localhost:%d", servicePID(t, newSource, "api").Port) {
				t.Fatalf("new preview output=%q", output.String())
			}
			state, err := next.ReadState()
			if err != nil || state == nil || state.Project != newSource.Project || state.Ports["api"] != servicePID(t, newSource, "api").Port {
				t.Fatalf("new preview state=%+v err=%v", state, err)
			}
		})
	}
}

type serviceOutput chan string

func (output serviceOutput) Write(data []byte) (int, error) {
	select {
	case output <- string(data):
	default:
	}
	return len(data), nil
}

func TestRunServiceRegistersOneServiceAndAttachesWithoutStoppingIt(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	serviceRunnerDatabase(t, s.Project, testBasePort+500)
	mustUp(t, s, &fakeProvider{services: []string{"web"}})
	web := servicePID(t, s, "web")
	st, err := s.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	target := Target{Root: s.Root, OwnerRoot: s.Root, Project: s.Project, StateDir: s.StateDir, Mode: s.Mode, Ports: st.Ports}
	for _, service := range docker.InfraServices {
		for _, port := range service.Ports {
			target.Ports[port.ComposeVar] = testBasePort + 500
		}
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	launch := &Launch{Configurations: []LaunchConfig{{
		Name: "API Server", Type: "node", Request: "launch", Cwd: s.Root,
		RuntimeExecutable: executable, Args: []string{"--port", "8080"}, Env: map[string]string{fakeServiceEnv: "1", "TMUX_PANE": "%1", "GEN_AI_API_KEY": "original"},
	}}}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- s.RunService(ctx, target, launch, "api", ServiceOptions{PreferredPort: testBasePort + 100, StopTimeout: time.Second})
	}()
	var api ServiceRecord
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		state, err := s.ReadState()
		if err != nil {
			t.Fatal(err)
		}
		for _, record := range state.Services {
			if record.Slug == "api" {
				api = record
			}
		}
		if api.PID > 0 && healthy(context.Background(), api.Health) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if api.PID == 0 || !isCurrent(api) || api.Port != testBasePort+100 || !isCurrent(web) {
		t.Fatalf("api=%+v web=%+v", api, web)
	}
	state, err := s.ReadState()
	if err != nil || len(state.Services) != 2 || state.Ports["api"] != api.Port {
		t.Fatalf("registered state=%+v err=%v", state, err)
	}
	attachCtx, detach := context.WithCancel(context.Background())
	output := make(serviceOutput, 1)
	attached := make(chan error, 1)
	preparations := 0
	attachLaunch := &Launch{Configurations: append([]LaunchConfig(nil), launch.Configurations...)}
	attachLaunch.Configurations[0].Env = map[string]string{fakeServiceEnv: "1", "TMUX_PANE": "%2", "GEN_AI_API_KEY": "original"}
	go func() {
		attached <- s.RunService(attachCtx, target, attachLaunch, "api", ServiceOptions{
			IO: ServiceIO{Stdout: output},
			BeforeStart: func(context.Context, Spec) error {
				preparations++
				return nil
			},
		})
	}()
	select {
	case text := <-output:
		if !strings.Contains(text, fmt.Sprint(api.Port)) {
			t.Fatalf("attached output=%q", text)
		}
	case err := <-attached:
		t.Fatalf("attach ended before output: %v", err)
	case <-time.After(5 * time.Second):
		t.Fatal("attach did not print the service log")
	}
	detach()
	if err := <-attached; err != nil || !isCurrent(api) {
		t.Fatalf("detach err=%v current=%v", err, isCurrent(api))
	}
	if preparations != 0 {
		t.Fatalf("attach prepared the existing service %d times", preparations)
	}
	if err := s.RunService(context.Background(), target, launch, "api", ServiceOptions{Args: []string{"changed"}}); err == nil || !strings.Contains(err.Error(), "another configuration") {
		t.Fatalf("changed args error=%v", err)
	}
	attachLaunch.Configurations[0].Env["GEN_AI_API_KEY"] = "changed"
	if err := s.RunService(context.Background(), target, attachLaunch, "api", ServiceOptions{}); err == nil || !strings.Contains(err.Error(), "another configuration") {
		t.Fatalf("changed application environment error=%v", err)
	}
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("foreground service did not stop")
	}
	if isCurrent(api) || !isCurrent(web) || servicePID(t, s, "api").PID != 0 {
		t.Fatalf("wrong services stopped: api=%+v web=%+v", servicePID(t, s, "api"), web)
	}
}

func TestRunServiceRefreshesItsSelectedDatabaseBinding(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	serviceRunnerDatabase(t, s.Project, testBasePort+501)
	target := Target{Root: s.Root, OwnerRoot: s.Root, Project: s.Project, StateDir: s.StateDir, Mode: s.Mode, Ports: map[string]int{}}
	for _, service := range docker.InfraServices {
		for _, port := range service.Ports {
			target.Ports[port.ComposeVar] = testBasePort + 500
		}
	}
	launch := &Launch{Configurations: []LaunchConfig{{
		Name: "API Server", Type: "node", Request: "launch", Cwd: s.Root,
		RuntimeExecutable: "/bin/sh", RuntimeArgs: []string{"-c", "printf '%s' \"$POSTGRES_PORT\""},
	}}}
	var output bytes.Buffer
	if err := s.RunService(context.Background(), target, launch, "api", ServiceOptions{PreferredPort: testBasePort + 200, IO: ServiceIO{Stdout: &output}}); err != nil {
		t.Fatal(err)
	}
	state, err := s.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	if want := fmt.Sprint(testBasePort + 501); output.String() != want || state.Ports["POSTGRES_HOST_PORT"] != testBasePort+501 {
		t.Fatalf("database binding: process port=%q state=%+v, want %s", output.String(), state.Ports, want)
	}
}

func runnerShellFixture(t *testing.T, body string, args ...string) (*Stack, Target, *Launch) {
	t.Helper()
	s := newTestStack(t, t.TempDir())
	target := Target{Root: s.Root, OwnerRoot: s.Root, Project: s.Project, StateDir: s.StateDir, Mode: s.Mode, Ports: map[string]int{}}
	for _, service := range docker.InfraServices {
		for _, port := range service.Ports {
			target.Ports[port.ComposeVar] = testBasePort + 500
		}
	}
	command := append([]string{"-c", body, "fixture"}, args...)
	launch := &Launch{Configurations: []LaunchConfig{{Name: "Model Server", Type: "node", Request: "launch", Cwd: s.Root, RuntimeExecutable: "/bin/sh", RuntimeArgs: command}}}
	return s, target, launch
}

func TestRunServiceCleansDescendantsAfterLeaderExit(t *testing.T) {
	for _, redirected := range []bool{false, true} {
		t.Run(fmt.Sprintf("redirected=%v", redirected), func(t *testing.T) {
			pidFile := filepath.Join(t.TempDir(), "child.pid")
			body := `sleep 30 & printf '%s' "$!" > "$1"`
			if redirected {
				body = `sleep 30 >/dev/null 2>&1 & printf '%s' "$!" > "$1"`
			}
			s, target, launch := runnerShellFixture(t, body, pidFile)
			t.Cleanup(func() {
				data, _ := os.ReadFile(pidFile)
				pid, _ := strconv.Atoi(string(data))
				if pid > 0 {
					_ = syscall.Kill(pid, syscall.SIGKILL)
				}
			})
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			err := s.RunService(ctx, target, launch, "model", ServiceOptions{PreferredPort: testBasePort + 200, IO: ServiceIO{Stdout: io.Discard, Stderr: io.Discard}})
			data, readErr := os.ReadFile(pidFile)
			if readErr != nil {
				t.Fatal(readErr)
			}
			pid, parseErr := strconv.Atoi(string(data))
			if err != nil || parseErr != nil || pidAlive(pid) {
				t.Fatalf("leader exit err=%v, child %d alive=%v, parse=%v", err, pid, pidAlive(pid), parseErr)
			}
			if rec := servicePID(t, s, "model"); rec.PGID != 0 {
				t.Fatalf("finished service retained live identity: %+v", rec)
			}
		})
	}
}

func TestRecordServiceExitRetainsSurvivingProcessGroup(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	pidFile := filepath.Join(t.TempDir(), "child.pid")
	sp := Spec{Name: "orphan fixture", Slug: "model", Dir: s.Root, Env: os.Environ(), Command: []string{"/bin/sh", "-c", `sleep 30 >/dev/null 2>&1 & printf '%s' "$!" > "$1"`, "fixture", pidFile}}
	record, err := startService(sp, filepath.Join(s.LogDir(), "model.log"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = syscall.Kill(-record.PGID, syscall.SIGKILL) })
	deadline := time.Now().Add(time.Second)
	for pidAlive(record.PID) {
		if time.Now().After(deadline) {
			t.Fatal("fixture leader did not exit")
		}
		time.Sleep(10 * time.Millisecond)
	}
	if err := s.WriteState(&State{Phase: PhaseReady, Services: []ServiceRecord{record}}); err != nil {
		t.Fatal(err)
	}
	if err := s.recordServiceExit(record, time.Second); err != nil {
		t.Fatal(err)
	}
	state, err := s.ReadState()
	if err != nil || len(state.Services) != 1 || state.Services[0].PGID != record.PGID || state.Phase != PhaseFailed {
		t.Fatalf("surviving group was forgotten: state=%+v err=%v", state, err)
	}
	_ = syscall.Kill(-record.PGID, syscall.SIGKILL)
	for groupAlive(record.PGID) {
		if time.Now().After(deadline) {
			t.Fatal("fixture group did not exit")
		}
		time.Sleep(10 * time.Millisecond)
	}
	if err := s.recordServiceExit(record, time.Second); err != nil {
		t.Fatal(err)
	}
	if saved := servicePID(t, s, "model"); saved.PGID != 0 {
		t.Fatalf("dead group identity retained: %+v", saved)
	}
}

func TestRunServiceRequiresHealthyAPIBeforeNewOwnerWeb(t *testing.T) {
	for _, apiHealthy := range []bool{false, true} {
		t.Run(fmt.Sprint(apiHealthy), func(t *testing.T) {
			s, target, launch := runnerShellFixture(t, `printf '%s' "$INTERNAL_URL"`)
			launch.Configurations[0].Name = "Web Server"
			target.Ports["api"] = testBasePort + 777
			state := &State{Services: []ServiceRecord{{Slug: "web"}, {Slug: "api"}}}
			var api ServiceRecord
			if apiHealthy {
				mustUp(t, s, &fakeProvider{services: []string{"api"}})
				api = servicePID(t, s, "api")
				var err error
				state, err = s.ReadState()
				if err != nil {
					t.Fatal(err)
				}
				state.Services = append(state.Services, ServiceRecord{Slug: "web"})
			}
			if err := s.WriteState(state); err != nil {
				t.Fatal(err)
			}
			prepared := false
			var output bytes.Buffer
			err := s.RunService(context.Background(), target, launch, "web", ServiceOptions{
				PreferredPort: testBasePort + 300, RequireAPI: true, IO: ServiceIO{Stdout: &output},
				BeforeStart: func(context.Context, Spec) error { prepared = true; return nil },
			})
			if !apiHealthy {
				if err == nil || !strings.Contains(err.Error(), "no healthy managed API") || prepared || output.Len() != 0 {
					t.Fatalf("unhealthy API: err=%v prepared=%v output=%q", err, prepared, output.String())
				}
				return
			}
			if want := fmt.Sprintf("http://localhost:%d", api.Port); err != nil || !prepared || output.String() != want || !isCurrent(api) {
				t.Fatalf("healthy API: err=%v prepared=%v output=%q, want %q", err, prepared, output.String(), want)
			}
		})
	}
}
