//go:build !windows

package devstack

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// fakeServiceEnv makes the test binary act as a service when set.
const fakeServiceEnv = "ODS_STACK_FAKE_SERVICE"

func TestMain(m *testing.M) {
	if os.Getenv(fakeServiceEnv) != "" {
		fakeServiceMain(os.Args[1:])
		return
	}
	os.Exit(m.Run())
}

// fakeServiceMain listens on --port, answers /health, and exits on SIGTERM.
// --ignore-term keeps running through SIGTERM; --spawn-child forks a copy
// with --ignore-term and no port, in the same process group.
func fakeServiceMain(args []string) {
	port := 0
	var raceMarker string
	var ignoreTerm, spawnChild bool
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--port":
			port, _ = strconv.Atoi(args[i+1])
			i++
		case "--ignore-term":
			ignoreTerm = true
		case "--spawn-child":
			spawnChild = true
		case "--race-once":
			raceMarker = args[i+1]
			i++
		}
	}
	if ignoreTerm {
		signal.Ignore(syscall.SIGTERM)
	}
	if spawnChild {
		exe, _ := os.Executable()
		child := exec.Command(exe, "--ignore-term")
		child.Env = os.Environ()
		if err := child.Start(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println("child", child.Process.Pid)
	}
	if port > 0 {
		if raceMarker != "" {
			file, err := os.OpenFile(raceMarker, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
			if err == nil {
				_, _ = fmt.Fprint(file, port)
				_ = file.Close()
				deadline := time.Now().Add(10 * time.Second)
				for {
					if _, err := os.Stat(raceMarker + ".ready"); err == nil {
						break
					}
					if time.Now().After(deadline) {
						os.Exit(2)
					}
					time.Sleep(10 * time.Millisecond)
				}
			}
		}
		ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		mux := http.NewServeMux()
		mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
		go func() { _ = http.Serve(ln, mux) }()
	}
	// Block on a signal channel so the runtime never sees a deadlock.
	hup := make(chan os.Signal, 1)
	signal.Notify(hup, syscall.SIGHUP)
	<-hup
}

// fakeProvider is a Provider that starts no infrastructure and plans fake
// services on the leased ports.
type fakeProvider struct {
	mu       sync.Mutex
	infra    []PortRequest
	services []string
	// extraArgs per service slug, such as "--spawn-child".
	extraArgs map[string][]string
	// fixedPorts per service slug: a port the service binds that is not
	// leased, as the Slack bot's metrics port.
	fixedPorts map[string]int
	// planHook runs at the start of Plan, inside the lifecycle lock.
	planHook  func()
	migrated  [][]string
	composeUp int
	prepared  int
}

func (p *fakeProvider) Prepare(context.Context) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.prepared++
	return nil
}

func (p *fakeProvider) InfraPorts() ([]PortRequest, error) { return p.infra, nil }

func (p *fakeProvider) AppPorts(Options) []PortRequest {
	var reqs []PortRequest
	for i, name := range p.services {
		reqs = append(reqs, PortRequest{Name: name, Preferred: testBasePort + i*10})
	}
	return reqs
}

func (p *fakeProvider) ComposeUp(context.Context, map[string]int, Options) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.composeUp++
	return nil
}

func (p *fakeProvider) ComposeDown(context.Context) error { return nil }

func (p *fakeProvider) Migrate(_ context.Context, env []string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.migrated = append(p.migrated, env)
	return nil
}

func (p *fakeProvider) Plan(_ string, ports map[string]int, env Env, _ Options) ([]Spec, error) {
	if p.planHook != nil {
		p.planHook()
	}
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	var specs []Spec
	for _, name := range p.services {
		port := ports[name]
		if fixed, ok := p.fixedPorts[name]; ok {
			port = fixed
		}
		cmd := append([]string{exe, "--port", fmt.Sprint(port)}, p.extraArgs[name]...)
		spec := Spec{
			Name:    name,
			Slug:    name,
			Command: cmd,
			Dir:     os.TempDir(),
			Env:     env.With([]string{fakeServiceEnv + "=1"}),
			Port:    port,
			Health:  fmt.Sprintf("http://localhost:%d/health", port),
		}
		if fixed, ok := p.fixedPorts[name]; ok {
			spec.Port, spec.FixedPort, spec.Optional, spec.Health = 0, fixed, true, ""
		}
		specs = append(specs, spec)
	}
	return specs, nil
}

func (p *fakeProvider) InfraEnv(ports map[string]int) map[string]string {
	values := map[string]string{}
	if port, ok := ports["POSTGRES_HOST_PORT"]; ok {
		values["POSTGRES_PORT"] = fmt.Sprint(port)
	}
	return values
}

// testBasePort is a free region chosen once per test binary.
var testBasePort = freeBasePort()

// newTestStack makes a git worktree with env templates and a stack whose
// registry lives in registryDir.
func newTestStack(t *testing.T, registryDir string) *Stack {
	t.Helper()
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "-q")
	vscode := filepath.Join(dir, ".vscode")
	if err := os.MkdirAll(vscode, 0o755); err != nil {
		t.Fatal(err)
	}
	for name, content := range map[string]string{
		"env_template.txt":     "GEN_AI_API_KEY=<REPLACE THIS>\nLANGSMITH_TRACING=\"true\"\nPOSTGRES_HOST=relational_db\n",
		"env.web_template.txt": "AUTH_TYPE=basic\n",
	} {
		if err := os.WriteFile(filepath.Join(vscode, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	s, err := Open(dir, "")
	if err != nil {
		t.Fatal(err)
	}
	s.Registry = &Registry{Dir: registryDir}
	t.Cleanup(func() {
		if err := s.stopServices(2 * time.Second); err != nil {
			t.Errorf("stack cleanup: %v", err)
		}
	})
	return s
}

func testOptions() Options {
	return Options{ReadyTimeout: 20 * time.Second, LockWait: 30 * time.Second, StopTimeout: 2 * time.Second, SkipPrepare: true}
}

func mustUp(t *testing.T, s *Stack, p *fakeProvider) *Status {
	t.Helper()
	status, err := s.Up(context.Background(), p, testOptions())
	if err != nil {
		t.Fatalf("up: %v (status %+v)", err, status)
	}
	if !status.Ready || status.Phase != PhaseReady {
		t.Fatalf("stack not ready: %+v", status)
	}
	return status
}

func servicePID(t *testing.T, s *Stack, slug string) ServiceRecord {
	t.Helper()
	st, err := s.ReadState()
	if err != nil || st == nil {
		t.Fatalf("read state: %v", err)
	}
	for _, rec := range st.Services {
		if rec.Slug == slug {
			return rec
		}
	}
	t.Fatalf("no record for %s", slug)
	return ServiceRecord{}
}

func TestUp_twoStacksGetDistinctPortsAndState(t *testing.T) {
	registry := t.TempDir()
	a := newTestStack(t, registry)
	b := newTestStack(t, registry)
	pa := &fakeProvider{services: []string{"web", "api"}, infra: []PortRequest{{Name: "POSTGRES_HOST_PORT", Preferred: testBasePort + 500}}}
	pb := &fakeProvider{services: []string{"web", "api"}, infra: []PortRequest{{Name: "POSTGRES_HOST_PORT", Preferred: testBasePort + 500}}}

	sa := mustUp(t, a, pa)
	sb := mustUp(t, b, pb)

	if a.Project == b.Project {
		t.Fatalf("projects collide: %s", a.Project)
	}
	if a.StateDir == b.StateDir {
		t.Fatalf("state dirs collide: %s", a.StateDir)
	}
	for _, name := range []string{"web", "api", "POSTGRES_HOST_PORT"} {
		if sa.Ports[name] == sb.Ports[name] {
			t.Errorf("%s port shared between stacks: %d", name, sa.Ports[name])
		}
	}
	if sa.URLs["web"] != fmt.Sprintf("http://localhost:%d", sa.Ports["web"]) {
		t.Errorf("web url %q does not match port %d", sa.URLs["web"], sa.Ports["web"])
	}
	// Migrations ran with the explicit local host and this stack's port.
	if len(pa.migrated) != 1 {
		t.Fatalf("migrations ran %d times", len(pa.migrated))
	}
	if got := EnvValue(pa.migrated[0], "POSTGRES_HOST"); got != "localhost" {
		t.Errorf("POSTGRES_HOST=%q, want localhost", got)
	}
	if got := EnvValue(pa.migrated[0], "POSTGRES_PORT"); got != fmt.Sprint(sa.Ports["POSTGRES_HOST_PORT"]) {
		t.Errorf("POSTGRES_PORT=%q, want %d", got, sa.Ports["POSTGRES_HOST_PORT"])
	}

	// Stopping one stack leaves the other running.
	if err := a.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}
	if st, _ := a.Status(); st.Ready || st.Phase != PhaseStopped || len(st.Services) != 0 {
		t.Errorf("stack a after stop: %+v", st)
	}
	st, err := b.Status()
	if err != nil {
		t.Fatal(err)
	}
	if !st.Ready {
		t.Errorf("stack b stopped too: %+v", st)
	}
	for _, svc := range st.Services {
		if svc.State != StateRunning || svc.Healthy == nil || !*svc.Healthy {
			t.Errorf("stack b service %s: %+v", svc.Slug, svc)
		}
	}

	// A restarted stack gets its ports back.
	again, err := a.Up(context.Background(), pa, testOptions())
	if err != nil {
		t.Fatal(err)
	}
	for name, port := range sa.Ports {
		if again.Ports[name] != port {
			t.Errorf("%s moved from %d to %d across restart", name, port, again.Ports[name])
		}
	}
	if len(pa.migrated) != 2 {
		t.Errorf("rerunning up skipped migrations: ran %d times", len(pa.migrated))
	}
}

func TestUp_concurrentSameStackConverges(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web", "api"}}

	var wg sync.WaitGroup
	results := make([]error, 2)
	for i := range results {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, results[i] = s.Up(context.Background(), p, testOptions())
		}()
	}
	wg.Wait()
	for i, err := range results {
		if err != nil {
			t.Fatalf("up %d: %v", i, err)
		}
	}
	st, err := s.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	if len(st.Services) != 2 {
		t.Fatalf("services after two ups: %d", len(st.Services))
	}
	pids := map[int]bool{}
	for _, rec := range st.Services {
		if !isCurrent(rec) {
			t.Errorf("%s is not running", rec.Slug)
		}
		pids[rec.PID] = true
	}
	if len(pids) != 2 {
		t.Errorf("expected two distinct processes, got %v", pids)
	}
	// The second run reused the first's processes rather than starting more
	// on the same ports: every leased port has exactly one listener.
	for _, rec := range st.Services {
		if bindable(rec.Port) {
			t.Errorf("port %d of %s is free", rec.Port, rec.Slug)
		}
	}
	if p.composeUp != 2 || p.migrated == nil {
		t.Errorf("compose ran %d times, migrations %d", p.composeUp, len(p.migrated))
	}
}

func TestUp_busyLeasedPortMovesService(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web"}}
	first := mustUp(t, s, p)
	if err := s.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}

	// Something else now holds the leased port.
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", first.Ports["web"]))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()

	second := mustUp(t, s, p)
	if second.Ports["web"] == first.Ports["web"] {
		t.Fatalf("web stayed on busy port %d", first.Ports["web"])
	}
	leases, err := s.Registry.Leases()
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range leases {
		if l.Name == "web" && l.Port != second.Ports["web"] {
			t.Errorf("registry lease %+v does not match new port %d", l, second.Ports["web"])
		}
	}
	rec := servicePID(t, s, "web")
	if rec.Port != second.Ports["web"] || !isCurrent(rec) {
		t.Errorf("web record %+v", rec)
	}
}

func TestUp_recoversInterruptedStart(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web", "api"}}
	mustUp(t, s, p)
	web := servicePID(t, s, "web")
	api := servicePID(t, s, "api")

	// Simulate an interrupted start: the api process died and the state was
	// left mid-start.
	if err := syscall.Kill(-api.PGID, syscall.SIGKILL); err != nil {
		t.Fatal(err)
	}
	for groupAlive(api.PGID) {
		time.Sleep(50 * time.Millisecond)
	}
	st, _ := s.ReadState()
	st.Phase = PhaseStarting
	if err := s.WriteState(st); err != nil {
		t.Fatal(err)
	}
	if status, _ := s.Status(); status.Ready {
		t.Fatalf("status reports ready with a dead service: %+v", status)
	}

	mustUp(t, s, p)
	if got := servicePID(t, s, "web"); got.PID != web.PID {
		t.Errorf("healthy web was restarted: pid %d -> %d", web.PID, got.PID)
	}
	if got := servicePID(t, s, "api"); got.PID == api.PID || !isCurrent(got) {
		t.Errorf("dead api was not restarted: %+v", got)
	}
}

func TestUp_reconcilesChangedSpecOnly(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web", "api"}, extraArgs: map[string][]string{}}
	mustUp(t, s, p)
	web := servicePID(t, s, "web")
	api := servicePID(t, s, "api")

	// The api command changes; web does not.
	p.extraArgs["api"] = []string{"--changed"}
	mustUp(t, s, p)
	if got := servicePID(t, s, "web"); got.PID != web.PID {
		t.Errorf("unchanged web was restarted: pid %d -> %d", web.PID, got.PID)
	}
	got := servicePID(t, s, "api")
	if got.PID == api.PID {
		t.Errorf("changed api kept pid %d", api.PID)
	}
	if pidAlive(api.PID) && isCurrent(api) {
		t.Errorf("old api process %d still runs", api.PID)
	}
}

func TestStop_killsDescendantsThatIgnoreTerm(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web"}, extraArgs: map[string][]string{"web": {"--spawn-child"}}}
	mustUp(t, s, p)
	web := servicePID(t, s, "web")
	deadline := time.Now().Add(5 * time.Second)
	for len(groupMembers(web.PGID)) < 2 {
		if time.Now().After(deadline) {
			t.Fatalf("child never appeared in group %d", web.PGID)
		}
		time.Sleep(50 * time.Millisecond)
	}

	if err := s.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}
	if groupAlive(web.PGID) {
		t.Errorf("process group %d still has members: %v", web.PGID, groupMembers(web.PGID))
	}
	if !bindable(web.Port) {
		t.Errorf("port %d still held after stop", web.Port)
	}
}

func TestStop_leavesForeignProcessesAlone(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	exe, _ := os.Executable()
	other := exec.Command(exe, "--port", "0")
	other.Env = append(os.Environ(), fakeServiceEnv+"=1")
	other.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := other.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = other.Process.Kill(); _, _ = other.Process.Wait() }()

	// A record that names a live pid with the wrong start identity.
	st := &State{Phase: PhaseReady, Services: []ServiceRecord{{
		Name: "web", Slug: "web", PID: other.Process.Pid, PGID: other.Process.Pid,
		StartMarker: "not the real marker", StartedAt: time.Now().Add(-time.Hour),
	}}}
	if err := s.WriteState(st); err != nil {
		t.Fatal(err)
	}
	if err := s.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}
	if !pidAlive(other.Process.Pid) {
		t.Fatal("stop killed a process it did not start")
	}
}

func TestLock_timesOutWithOwner(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	unlock, err := s.Lock(context.Background(), "test holder", time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer unlock()
	_, err = s.Lock(context.Background(), "second", 300*time.Millisecond)
	if !errors.Is(err, ErrLocked) {
		t.Fatalf("second lock: %v", err)
	}
	if got := err.Error(); !contains(got, "test holder") {
		t.Errorf("error does not name the owner: %s", got)
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(sub) == 0 || indexOf(s, sub) >= 0)
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

func TestUp_keepsServiceOnFixedPortItHolds(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	fixed := freeBasePort() + 5
	p := &fakeProvider{services: []string{"web", "bot"}, fixedPorts: map[string]int{"bot": fixed}}
	mustUp(t, s, p)
	bot := servicePID(t, s, "bot")
	if bot.PID == 0 || bot.Skipped != "" {
		t.Fatalf("bot not started: %+v", bot)
	}

	// The bot itself now holds its fixed port; a second up must keep it.
	mustUp(t, s, p)
	again := servicePID(t, s, "bot")
	if again.PID != bot.PID || again.Skipped != "" {
		t.Errorf("bot restarted or skipped on rerun: %+v -> %+v", bot, again)
	}

	// Once something else holds the port, the bot is skipped, not killed
	// wrongly: stop first so the port is free for the foreign listener.
	if err := s.Stop(context.Background(), testOptions()); err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", fixed))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	mustUp(t, s, p)
	if skipped := servicePID(t, s, "bot"); skipped.Skipped == "" {
		t.Errorf("bot not skipped while port is foreign: %+v", skipped)
	}
}

func TestStatus_notReadyWhileStartIsIncomplete(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web"}}
	mustUp(t, s, p)
	st, _ := s.ReadState()
	// An interrupted start saved a healthy web but never reached the rest.
	st.Phase = PhaseStarting
	if err := s.WriteState(st); err != nil {
		t.Fatal(err)
	}
	status, err := s.Status()
	if err != nil {
		t.Fatal(err)
	}
	if status.Ready {
		t.Fatalf("incomplete start reported ready: %+v", status)
	}
	mustUp(t, s, p)
	if status, _ := s.Status(); !status.Ready {
		t.Fatalf("finished start not ready: %+v", status)
	}
}

func TestRestart_holdsOneLock(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web"}}
	first := mustUp(t, s, p)

	// Plan runs inside the locked restart, after the services were stopped:
	// a competing lifecycle command must be refused at that point.
	var lockErr error
	hooked := false
	p.planHook = func() {
		hooked = true
		var unlock func()
		unlock, lockErr = s.Lock(context.Background(), "intruder", 100*time.Millisecond)
		if lockErr == nil {
			unlock()
		}
	}
	status, err := s.Restart(context.Background(), p, testOptions())
	if err != nil || !status.Ready {
		t.Fatalf("restart: %v %+v", err, status)
	}
	if !hooked {
		t.Fatal("plan hook did not run")
	}
	if !errors.Is(lockErr, ErrLocked) {
		t.Errorf("another command could take the lock during restart: %v", lockErr)
	}
	if status.Ports["web"] != first.Ports["web"] {
		t.Errorf("restart changed the port: %d -> %d", first.Ports["web"], status.Ports["web"])
	}
}
