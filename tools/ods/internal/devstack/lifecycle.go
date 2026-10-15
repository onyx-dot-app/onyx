package devstack

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
)

// Provider supplies the environment-specific steps of a lifecycle: the tool
// checks, Compose, migrations and the service plan. The command wires the
// real one; tests inject fakes.
type Provider interface {
	// Prepare installs dependencies and checks the host tools.
	Prepare(ctx context.Context) error
	// InfraPorts lists the infrastructure host ports to lease. A request is
	// Fixed when the worktree's container already runs on a port.
	InfraPorts() ([]PortRequest, error)
	// AppPorts lists the application host ports to lease for the plan.
	AppPorts(opts Options) []PortRequest
	// ComposeUp starts the infrastructure containers on the leased ports.
	ComposeUp(ctx context.Context, ports map[string]int, opts Options) error
	// ComposeDown stops the infrastructure containers.
	ComposeDown(ctx context.Context) error
	// Migrate runs the database migrations with env.
	Migrate(ctx context.Context, env []string) error
	// Plan resolves the services to run. env carries the shell environment
	// and the stack's own overrides, which every service gets.
	Plan(root string, ports map[string]int, env Env, opts Options) ([]Spec, error)
	// InfraEnv maps leased infrastructure ports to the app variables, such
	// as POSTGRES_PORT, written to .vscode/.env and the service env.
	InfraEnv(ports map[string]int) map[string]string
}

// Options tune one lifecycle run.
type Options struct {
	Profile          string
	LocalModelServer bool
	// ReadyTimeout bounds the wait for health checks.
	ReadyTimeout time.Duration
	// LockWait bounds the wait for another lifecycle holder.
	LockWait time.Duration
	// StopTimeout is the grace period before SIGKILL.
	StopTimeout time.Duration
	// SkipPrepare skips dependency installation.
	SkipPrepare bool
	// BindRetries is how many times a service whose leased port turned
	// out busy is moved to a new port.
	BindRetries int
	// SettleTime is how long a service without a health check must stay
	// alive before the stack counts as ready, so a crash on startup is
	// reported rather than hidden by a fast exit.
	SettleTime time.Duration
}

// WithDefaults fills the fields that have no CLI flag. The timeouts keep
// their value, so an explicit zero means no wait.
func (o Options) WithDefaults() Options {
	if o.Profile == "" {
		o.Profile = "default"
	}
	if o.BindRetries == 0 {
		o.BindRetries = 3
	}
	if o.SettleTime == 0 {
		o.SettleTime = 5 * time.Second
	}
	return o
}

// Up prepares the worktree, starts infrastructure, migrates, and starts or
// reconciles the application services, then waits for readiness.
func (s *Stack) Up(ctx context.Context, p Provider, opts Options) (*Status, error) {
	return s.run(ctx, p, opts, true)
}

// Start starts or reconciles the application services against the
// infrastructure that Up already started.
func (s *Stack) Start(ctx context.Context, p Provider, opts Options) (*Status, error) {
	return s.run(ctx, p, opts, false)
}

func (s *Stack) run(ctx context.Context, p Provider, opts Options, infra bool) (*Status, error) {
	opts = opts.WithDefaults()
	unlock, err := s.Lock(ctx, "stack up", opts.LockWait)
	if err != nil {
		return nil, err
	}
	defer unlock()
	return s.runLocked(ctx, p, opts, infra)
}

// runLocked is run with the lifecycle lock already held.
func (s *Stack) runLocked(ctx context.Context, p Provider, opts Options, infra bool) (*Status, error) {
	st, err := s.ReadState()
	if err != nil {
		return nil, err
	}
	if st == nil {
		st = &State{Ports: map[string]int{}}
	}
	if st.Profile != "" && st.Profile != opts.Profile {
		log.Infof("Switching profile from %s to %s", st.Profile, opts.Profile)
	}
	st.Profile = opts.Profile
	st.SettleTime = opts.SettleTime
	st.Errors = nil
	st.Phase = PhasePreparing
	if err := s.WriteState(st); err != nil {
		return nil, err
	}
	if _, _, err := PrepareEnvFiles(s.Root); err != nil {
		return nil, s.fail(st, err)
	}
	if !opts.SkipPrepare {
		if err := p.Prepare(ctx); err != nil {
			return nil, s.fail(st, err)
		}
	}

	var requests []PortRequest
	if infra {
		infraRequests, err := p.InfraPorts()
		if err != nil {
			return nil, s.fail(st, err)
		}
		requests = append(requests, infraRequests...)
	} else if len(st.Ports) == 0 {
		return nil, s.fail(st, errors.New("no infrastructure ports recorded; run `ods stack up` first"))
	}
	requests = append(requests, p.AppPorts(opts)...)
	if err := s.leasePorts(st, requests); err != nil {
		return nil, s.fail(st, err)
	}

	if infra {
		st.Phase = PhaseInfra
		if err := s.WriteState(st); err != nil {
			return nil, err
		}
		if err := p.ComposeUp(ctx, st.Ports, opts); err != nil {
			return nil, s.fail(st, err)
		}
	}

	env, fileEnv, err := s.serviceEnv(p, st.Ports, opts)
	if err != nil {
		return nil, s.fail(st, err)
	}

	if infra {
		st.Phase = PhaseMigrating
		if err := s.WriteState(st); err != nil {
			return nil, err
		}
		if err := p.Migrate(ctx, env.With(fileEnv)); err != nil {
			return nil, s.fail(st, fmt.Errorf("migrations: %w", err))
		}
	}

	st.Phase = PhaseStarting
	if err := s.WriteState(st); err != nil {
		return nil, err
	}
	for attempt := 0; ; attempt++ {
		specs, err := p.Plan(s.Root, st.Ports, env, opts)
		if err != nil {
			return nil, s.fail(st, err)
		}
		busy, err := s.reconcile(st, specs, opts.StopTimeout)
		if err != nil {
			return nil, s.fail(st, err)
		}
		if len(busy) == 0 {
			status, readyErr := s.waitReady(ctx, st, opts.ReadyTimeout, opts.SettleTime)
			var conflict *bindFailure
			if !errors.As(readyErr, &conflict) {
				return status, readyErr
			}
			busy = conflict.services
		}
		if attempt >= opts.BindRetries {
			return nil, s.fail(st, fmt.Errorf("ports still busy after %d retries: %s", opts.BindRetries, strings.Join(busy, ", ")))
		}
		log.Warnf("Leased ports are busy (%s), leasing new ones", strings.Join(busy, ", "))
		for i, rec := range st.Services {
			for _, name := range busy {
				if rec.Slug != name {
					continue
				}
				if left := stopRecords([]ServiceRecord{rec}, opts.StopTimeout); len(left) > 0 {
					return nil, s.fail(st, fmt.Errorf("cannot stop %s before bind retry", rec.Name))
				}
				st.Services[i].PID = 0
				st.Services[i].PGID = 0
			}
		}
		var retry []PortRequest
		for _, req := range p.AppPorts(opts) {
			for _, name := range busy {
				if req.Name == name {
					delete(st.Ports, name)
					retry = append(retry, req)
				}
			}
		}
		if err := s.leasePorts(st, retry); err != nil {
			return nil, s.fail(st, err)
		}
		if env, _, err = s.serviceEnv(p, st.Ports, opts); err != nil {
			return nil, s.fail(st, err)
		}
	}
}

type bindFailure struct {
	services []string
}

func (e *bindFailure) Error() string {
	return "services failed to bind: " + strings.Join(e.services, ", ")
}

func failedBind(rec ServiceRecord) bool {
	if rec.Port <= 0 || rec.Log == "" {
		return false
	}
	data, err := readLogTail(rec.Log)
	if err != nil {
		return false
	}
	output := strings.ToLower(string(data))
	return strings.Contains(output, "address already in use") || strings.Contains(output, "eaddrinuse")
}

func (s *Stack) fail(st *State, err error) error {
	st.Phase = PhaseFailed
	st.Errors = append(st.Errors, err.Error())
	if werr := s.WriteState(st); werr != nil {
		log.Warnf("Failed to write state: %v", werr)
	}
	return err
}

// leasePorts leases requests. A port that one of this stack's own running
// services holds is kept as is; the registry rechecks every other lease.
func (s *Stack) leasePorts(st *State, requests []PortRequest) error {
	if s.Registry == nil {
		return errors.New("no port registry")
	}
	for i, req := range requests {
		for _, rec := range st.Services {
			if !isCurrent(rec) {
				continue
			}
			port := 0
			switch req.Name {
			case rec.Slug:
				port = rec.Port
			case rec.Slug + "-metrics":
				port = st.Ports[req.Name]
			}
			// A port stays fixed only while this stack's own process group
			// holds it; a port lost to another process is leased again.
			if port > 0 && portHeldByGroup(port, rec.PGID) {
				requests[i].Fixed = port
			}
		}
	}
	ports, err := s.Registry.Lease(s.Root, requests)
	if err != nil {
		return err
	}
	for name, port := range ports {
		st.Ports[name] = port
	}
	return s.WriteState(st)
}

// Env is the layered environment of a service: Base is the shell, and
// Overrides are the hosts and leased ports of this stack, which win over any
// env file or launch configuration in between.
type Env struct {
	Base      []string
	Overrides []string
}

// With resolves the environment with layers applied between Base and
// Overrides, in order.
func (e Env) With(layers ...[]string) []string {
	env := e.Base
	for _, layer := range layers {
		env = MergeEnv(env, layer)
	}
	return MergeEnv(env, e.Overrides)
}

// serviceEnv builds the environment every service inherits, and returns the
// entries of .vscode/.env separately. The infrastructure port variables are
// also written to .vscode/.env for commands run by hand.
func (s *Stack) serviceEnv(p Provider, ports map[string]int, opts Options) (Env, []string, error) {
	values := p.InfraEnv(ports)
	envPath := filepath.Join(s.Root, ".vscode", ".env")
	if err := UpsertEnvFile(envPath, values); err != nil {
		return Env{}, nil, err
	}
	fileEnv, err := LoadEnvFile(envPath)
	if err != nil {
		return Env{}, nil, err
	}
	overrides := map[string]string{
		"POSTGRES_HOST":              "localhost",
		"REDIS_HOST":                 "localhost",
		"OPENSEARCH_HOST":            "localhost",
		"MODEL_SERVER_HOST":          "localhost",
		"INDEXING_MODEL_SERVER_HOST": "localhost",
	}
	for k, v := range values {
		overrides[k] = v
	}
	for name, port := range ports {
		switch name {
		case "web":
			overrides["PORT"] = fmt.Sprint(port)
			overrides["WEB_DOMAIN"] = fmt.Sprintf("http://localhost:%d", port)
		case "api":
			overrides["INTERNAL_URL"] = fmt.Sprintf("http://localhost:%d", port)
		case "mcp":
			overrides["MCP_SERVER_PORT"] = fmt.Sprint(port)
			overrides["MCP_INTERNAL_URL"] = fmt.Sprintf("http://localhost:%d", port)
		case "model":
			if opts.LocalModelServer {
				overrides["MODEL_SERVER_PORT"] = fmt.Sprint(port)
			}
		}
	}
	return Env{Base: environ(), Overrides: mapToEnv(overrides)}, fileEnv, nil
}

// reconcile makes the running services match specs. A record whose process
// is current and whose spec hash is unchanged is kept; every other record is
// stopped and its spec started. It returns the names of ports that a new
// service could not bind because the port is busy.
func (s *Stack) reconcile(st *State, specs []Spec, stopTimeout time.Duration) ([]string, error) {
	wanted := map[string]Spec{}
	for _, sp := range specs {
		wanted[sp.Slug] = sp
	}

	var kept []ServiceRecord
	var stale []ServiceRecord
	for _, rec := range st.Services {
		sp, ok := wanted[rec.Slug]
		if ok && sp.Skip == "" && rec.Skipped == "" && rec.SpecHash == sp.Hash() && isCurrent(rec) {
			kept = append(kept, rec)
			continue
		}
		log.Debugf("%s is stale: wanted=%v hash=%s/%s current=%v", rec.Slug, ok, rec.SpecHash, sp.Hash(), isCurrent(rec))
		if rec.PGID > 0 {
			stale = append(stale, rec)
		}
	}
	if len(stale) > 0 {
		names := make([]string, 0, len(stale))
		for _, rec := range stale {
			names = append(names, rec.Name)
		}
		log.Infof("Stopping stale services: %s", strings.Join(names, ", "))
		if left := stopRecords(stale, stopTimeout); len(left) > 0 {
			for _, rec := range left {
				return nil, fmt.Errorf("could not stop %s (pgid %d)", rec.Name, rec.PGID)
			}
		}
	}
	st.Services = kept
	if err := s.WriteState(st); err != nil {
		return nil, err
	}

	keptSlugs := map[string]bool{}
	for _, rec := range kept {
		keptSlugs[rec.Slug] = true
	}
	var busy []string
	for _, sp := range specs {
		if keptSlugs[sp.Slug] {
			continue
		}
		if sp.Skip == "" && sp.FixedPort > 0 && !bindable(sp.FixedPort) {
			sp.Skip = fmt.Sprintf("its port %d is in use", sp.FixedPort)
		}
		if sp.Skip != "" {
			log.Infof("Skipping %s: %s", sp.Name, sp.Skip)
			st.Services = append(st.Services, ServiceRecord{Name: sp.Name, Slug: sp.Slug, Skipped: sp.Skip, Optional: sp.Optional, SpecHash: sp.Hash()})
			continue
		}
		if sp.Port > 0 && !bindable(sp.Port) {
			busy = append(busy, sp.Slug)
			continue
		}
		rec, err := startService(sp, filepath.Join(s.LogDir(), sp.Slug+".log"))
		if err != nil {
			return nil, err
		}
		log.Infof("Started %s (pid %d), log: %s", sp.Name, rec.PID, rec.Log)
		st.Services = append(st.Services, rec)
		if err := s.WriteState(st); err != nil {
			return nil, err
		}
	}
	sortRecords(st.Services, specs)
	return busy, s.WriteState(st)
}

func sortRecords(recs []ServiceRecord, specs []Spec) {
	order := map[string]int{}
	for i, sp := range specs {
		order[sp.Slug] = i
	}
	sort.SliceStable(recs, func(i, j int) bool { return order[recs[i].Slug] < order[recs[j].Slug] })
}

// Stop stops the managed services and keeps the infrastructure running.
func (s *Stack) Stop(ctx context.Context, opts Options) error {
	opts = opts.WithDefaults()
	unlock, err := s.Lock(ctx, "stack stop", opts.LockWait)
	if err != nil {
		return err
	}
	defer unlock()
	return s.stopServices(opts.StopTimeout)
}

func (s *Stack) stopServices(timeout time.Duration) error {
	st, err := s.ReadState()
	if err != nil || st == nil {
		return err
	}
	left := stopRecords(st.Services, timeout)
	st.Services = left
	st.Phase = PhaseStopped
	if len(left) > 0 {
		st.Phase = PhaseFailed
		names := make([]string, 0, len(left))
		for _, rec := range left {
			names = append(names, rec.Name)
		}
		err = fmt.Errorf("could not stop: %s", strings.Join(names, ", "))
		st.Errors = append(st.Errors, err.Error())
	}
	if werr := s.WriteState(st); werr != nil {
		return werr
	}
	return err
}

// Down stops the services and the infrastructure. Volumes and port leases
// are kept so the next Up reuses them.
func (s *Stack) Down(ctx context.Context, p Provider, opts Options) error {
	opts = opts.WithDefaults()
	unlock, err := s.Lock(ctx, "stack down", opts.LockWait)
	if err != nil {
		return err
	}
	defer unlock()
	if err := s.stopServices(opts.StopTimeout); err != nil {
		return err
	}
	return p.ComposeDown(ctx)
}

// Restart stops the services and starts them again against the running
// infrastructure.
func (s *Stack) Restart(ctx context.Context, p Provider, opts Options) (*Status, error) {
	opts = opts.WithDefaults()
	unlock, err := s.Lock(ctx, "stack restart", opts.LockWait)
	if err != nil {
		return nil, err
	}
	defer unlock()
	if err := s.stopServices(opts.StopTimeout); err != nil {
		return nil, err
	}
	return s.runLocked(ctx, p, opts, false)
}

// ServiceStatus is one service as reported by Status.
type ServiceStatus struct {
	Name     string `json:"name"`
	Slug     string `json:"slug"`
	State    string `json:"state"`
	PID      int    `json:"pid,omitempty"`
	Port     int    `json:"port,omitempty"`
	Health   string `json:"health,omitempty"`
	Healthy  *bool  `json:"healthy,omitempty"`
	Log      string `json:"log,omitempty"`
	Reason   string `json:"reason,omitempty"`
	Optional bool   `json:"optional,omitempty"`
	// LogTail holds the last lines of the log of a service that exited or
	// is unhealthy, so a failure can be read from the status alone.
	LogTail string `json:"log_tail,omitempty"`
}

// Service states.
const (
	StateRunning = "running"
	StateExited  = "exited"
	StateSkipped = "skipped"
)

// Status is the live view of a stack.
type Status struct {
	Root     string            `json:"root"`
	Project  string            `json:"project"`
	Profile  string            `json:"profile"`
	Phase    string            `json:"phase"`
	Ready    bool              `json:"ready"`
	Ports    map[string]int    `json:"ports"`
	URLs     map[string]string `json:"urls"`
	Services []ServiceStatus   `json:"services"`
	Errors   []string          `json:"errors"`
	StateDir string            `json:"state_dir"`

	// healthyNow is Ready without the phase condition, for the readiness
	// wait while the phase is still starting.
	healthyNow bool
}

// Status reports the current state without taking the lock. It returns nil
// when the stack has never been started.
func (s *Stack) Status() (*Status, error) {
	st, err := s.ReadState()
	if err != nil || st == nil {
		return nil, err
	}
	return s.status(st, true), nil
}

// status is statusCtx without a deadline, for calls outside a readiness
// wait.
func (s *Stack) status(st *State, probe bool) *Status {
	return s.statusCtx(context.Background(), st, probe)
}

// statusCtx computes the live status. Health probes are bounded by ctx.
func (s *Stack) statusCtx(ctx context.Context, st *State, probe bool) *Status {
	out := &Status{
		Root:     s.Root,
		Project:  s.Project,
		Profile:  st.Profile,
		Phase:    st.Phase,
		Ports:    st.Ports,
		URLs:     URLs(st.Ports),
		Errors:   st.Errors,
		StateDir: s.StateDir,
	}
	if out.Errors == nil {
		out.Errors = []string{}
	}
	ready := len(st.Services) > 0
	for _, rec := range st.Services {
		ss := ServiceStatus{Name: rec.Name, Slug: rec.Slug, PID: rec.PID, Port: rec.Port, Health: rec.Health, Log: rec.Log, Optional: rec.Optional}
		switch {
		case rec.Skipped != "":
			ss.State, ss.Reason, ss.PID = StateSkipped, rec.Skipped, 0
		case isCurrent(rec):
			ss.State = StateRunning
			if rec.Health != "" && probe {
				healthy := healthy(ctx, rec.Health)
				ss.Healthy = &healthy
				if !healthy {
					ss.LogTail = logTail(rec.Log, logTailLines)
					if !rec.Optional {
						ready = false
					}
				}
			}
		default:
			ss.State = StateExited
			ss.LogTail = logTail(rec.Log, logTailLines)
			if !rec.Optional {
				ready = false
			}
		}
		out.Services = append(out.Services, ss)
	}
	if out.Services == nil {
		out.Services = []ServiceStatus{}
	}
	settle := st.SettleTime
	if settle == 0 {
		settle = Options{}.WithDefaults().SettleTime
	}
	out.healthyNow = ready && settled(st.Services, settle)
	// A stack is ready only after a reconcile finished: an interrupted
	// start may have saved just part of the profile.
	out.Ready = out.healthyNow && (st.Phase == PhaseReady || st.Phase == PhaseDegraded)
	return out
}

// settled reports whether every required service without a health check
// has been alive for at least settle.
func settled(recs []ServiceRecord, settle time.Duration) bool {
	for _, rec := range recs {
		if rec.Skipped != "" || rec.Optional || rec.Health != "" {
			continue
		}
		if time.Since(rec.StartedAt) < settle {
			return false
		}
	}
	return true
}

// URLs lists the stack's entry points by port name.
func URLs(ports map[string]int) map[string]string {
	urls := map[string]string{}
	for name, port := range ports {
		switch name {
		case "web", "api", "mcp", "model":
			urls[name] = fmt.Sprintf("http://localhost:%d", port)
		}
	}
	return urls
}

// logTailLines is how many log lines a failing service reports.
const logTailLines = 30

const maxLogTailBytes = 64 * 1024

func readLogTail(path string) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer func() { _ = file.Close() }()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if info.Size() > maxLogTailBytes {
		if _, err := file.Seek(info.Size()-maxLogTailBytes, io.SeekStart); err != nil {
			return nil, err
		}
	}
	return io.ReadAll(io.LimitReader(file, maxLogTailBytes))
}

// logTail returns the last n lines of a log file, or "" when unreadable.
func logTail(path string, n int) string {
	if path == "" || n <= 0 {
		return ""
	}
	data, err := readLogTail(path)
	if err != nil {
		return ""
	}
	lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	return strings.Join(lines, "\n")
}

// healthy reports whether url answers 200 within 3 seconds and before ctx
// ends, whichever comes first.
func healthy(ctx context.Context, url string) bool {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return false
	}
	_ = resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// waitReady polls the services until every required one is running and
// healthy and has been alive for settle, or a required one exited, or the
// timeout passes.
func (s *Stack) waitReady(ctx context.Context, st *State, timeout, settle time.Duration) (*Status, error) {
	deadline := time.Now().Add(timeout)
	// Health probes never run past the deadline.
	probeCtx, cancel := context.WithDeadline(ctx, deadline)
	defer cancel()
	for {
		var conflicts []string
		for i := range st.Services {
			rec := &st.Services[i]
			rememberGroup(rec)
			if failedBind(*rec) {
				conflicts = append(conflicts, rec.Slug)
			}
		}
		if err := s.WriteState(st); err != nil {
			return nil, err
		}
		status := s.statusCtx(probeCtx, st, true)
		if len(conflicts) > 0 {
			return status, &bindFailure{services: conflicts}
		}
		var exited []string
		for _, ss := range status.Services {
			if ss.State == StateExited && !ss.Optional {
				exited = append(exited, ss.Name)
			}
		}
		if len(exited) > 0 {
			err := s.fail(st, fmt.Errorf("services exited during startup: %s", strings.Join(exited, ", ")))
			return s.status(st, true), err
		}
		if status.healthyNow {
			st.Phase = PhaseReady
			if err := s.WriteState(st); err != nil {
				return status, err
			}
			// Return the snapshot that passed, not a fresh probe that could
			// disagree with the nil error.
			status.Phase = PhaseReady
			status.Ready = true
			return status, nil
		}
		if time.Now().After(deadline) {
			st.Phase = PhaseDegraded
			err := fmt.Errorf("stack not ready after %s", timeout)
			st.Errors = append(st.Errors, err.Error())
			if werr := s.WriteState(st); werr != nil {
				return status, werr
			}
			// Report the probe that timed out; do not probe again.
			status.Phase = PhaseDegraded
			status.Errors = st.Errors
			return status, err
		}
		select {
		case <-ctx.Done():
			return status, ctx.Err()
		case <-time.After(time.Second):
		}
	}
}
