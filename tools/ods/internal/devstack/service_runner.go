package devstack

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

// ServiceIO connects a foreground service to its terminal while retaining logs.
type ServiceIO struct {
	Stdin  io.Reader
	Stdout io.Writer
	Stderr io.Writer
}

type ServiceOptions struct {
	PreferredPort int
	Args          []string
	IO            ServiceIO
	BeforeStart   func(context.Context, Spec) error
	RequireAPI    bool
	LockWait      time.Duration
	StopTimeout   time.Duration
}

type serviceCleanupError struct {
	record ServiceRecord
}

func (err *serviceCleanupError) Error() string {
	return fmt.Sprintf("cannot stop surviving processes for %s (group %d)", err.record.Name, err.record.PGID)
}

// RunService starts one service without reconciling the other services in its stack.
// An existing process is attached to, and remains running when the caller detaches.
func (s *Stack) RunService(ctx context.Context, target Target, launch *Launch, slug string, opts ServiceOptions) error {
	defaults := (Options{LockWait: opts.LockWait, StopTimeout: opts.StopTimeout}).WithDefaults()
	opts.LockWait, opts.StopTimeout = defaults.LockWait, defaults.StopTimeout
	startup, cancelStartup := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
	defer cancelStartup()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)
	releaseSource := func() {}
	var err error
	if s.Mode == Frontend {
		releaseSource, err = s.lockFrontendService(startup, target, defaults.LockWait)
		if err != nil {
			return err
		}
	}
	unlock, err := s.Lock(startup, "run "+slug, defaults.LockWait)
	if err != nil {
		releaseSource()
		return err
	}
	releaseInfrastructure := func() {}
	if s.Mode != Frontend {
		releaseInfrastructure, err = s.LockInfrastructure(startup, defaults.LockWait)
		if err != nil {
			unlock()
			releaseSource()
			return err
		}
	}
	record, done, err := s.startSingleService(startup, target, launch, slug, opts)
	releaseInfrastructure()
	unlock()
	releaseSource()
	if err != nil {
		return err
	}
	if done == nil {
		return attachService(startup, record, opts.IO.Stdout, signals)
	}
	select {
	case err = <-done:
	case sig := <-signals:
		err = finishService(record, done, sig, defaults.StopTimeout)
	case <-ctx.Done():
		err = finishService(record, done, os.Interrupt, defaults.StopTimeout)
	}
	var cleanupErr *serviceCleanupError
	if errors.As(err, &cleanupErr) {
		record = cleanupErr.record
	}
	return errors.Join(err, s.recordServiceExit(record, defaults.LockWait))
}

func (s *Stack) startSingleService(ctx context.Context, target Target, launch *Launch, slug string, opts ServiceOptions) (ServiceRecord, <-chan error, error) {
	if err := ctx.Err(); err != nil {
		return ServiceRecord{}, nil, err
	}
	st, err := s.ReadState()
	if err != nil {
		return ServiceRecord{}, nil, err
	}
	var running *ServiceRecord
	if st != nil && st.Project != s.Project && s.Mode == Frontend {
		for _, record := range st.Services {
			if isCurrent(record) || groupAlive(record.PGID) {
				return ServiceRecord{}, nil, fmt.Errorf("frontend already uses project %s; stop it before selecting %s", st.Project, s.Project)
			}
		}
		st = &State{Ports: map[string]int{}}
	}
	if st != nil {
		if st.Project != s.Project {
			return ServiceRecord{}, nil, fmt.Errorf("recorded project is %s; stop it before selecting project %s", st.Project, s.Project)
		}
		for _, record := range st.Services {
			if record.Slug == slug && isCurrent(record) {
				running = &record
				break
			}
		}
		if st.Root != "" && st.Root != s.Root {
			return ServiceRecord{}, nil, s.ownerError(st)
		}
	} else {
		st = &State{Ports: map[string]int{}}
	}
	if s.Mode != Frontend && target.OwnerRoot != "" && target.OwnerRoot != s.Root {
		return ServiceRecord{}, nil, fmt.Errorf("run %s from the API checkout %s", slug, target.OwnerRoot)
	}
	if st.Ports == nil {
		st.Ports = map[string]int{}
	}
	for name, port := range target.Ports {
		if st.Ports[name] == 0 || (s.Mode == Frontend && name != "web") {
			st.Ports[name] = port
		}
	}
	if running == nil && slug == "web" && opts.RequireAPI {
		backend := st
		if s.Mode == Frontend {
			backend, err = (&Stack{StateDir: target.StateDir}).ReadState()
			if err != nil {
				return ServiceRecord{}, nil, err
			}
		}
		apiPort := 0
		if backend != nil && backend.Project == target.Project {
			for _, service := range backend.Services {
				if service.Slug == "api" && isCurrent(service) && service.Port > 0 && service.Health != "" && healthy(ctx, service.Health) {
					apiPort = service.Port
					break
				}
			}
		}
		if apiPort == 0 {
			return ServiceRecord{}, nil, fmt.Errorf("no healthy managed API for project %s; run 'ods stack up' or 'ods backend api' first", target.Project)
		}
		st.Ports["api"] = apiPort
	}
	preferred := opts.PreferredPort
	if preferred == 0 {
		switch slug {
		case "web":
			preferred = 3000
		case "api":
			preferred = 8080
		case "model":
			preferred = 9000
		}
	}
	if preferred < 1 || preferred > 65535 {
		return ServiceRecord{}, nil, fmt.Errorf("invalid port %d", preferred)
	}
	if running != nil && opts.PreferredPort > 0 && running.Port != opts.PreferredPort {
		return ServiceRecord{}, nil, fmt.Errorf("%s already runs on port %d; stop it before selecting port %d", slug, running.Port, opts.PreferredPort)
	}
	if slug == "api" {
		port, err := docker.GetHostPort(docker.ContainerName(target.Project, "relational_db"), 5432)
		if err != nil {
			return ServiceRecord{}, nil, fmt.Errorf("database for project %s is not available; run 'ods stack up' first: %v", target.Project, err)
		}
		st.Ports["POSTGRES_HOST_PORT"] = port
	}
	if running == nil && opts.PreferredPort > 0 && st.Ports[slug] != opts.PreferredPort {
		delete(st.Ports, slug)
	}
	if err := s.leasePorts(st, []PortRequest{{Name: slug, Preferred: preferred, Replace: running == nil && opts.PreferredPort > 0}}); err != nil {
		return ServiceRecord{}, nil, err
	}
	target.Ports = make(map[string]int, len(st.Ports))
	for name, port := range st.Ports {
		target.Ports[name] = port
	}
	if slug != "model" {
		modelServices := st.Services
		if s.Mode == Frontend && target.StateDir != s.StateDir {
			source, err := (&Stack{StateDir: target.StateDir}).ReadState()
			if err != nil {
				return ServiceRecord{}, nil, err
			}
			modelServices = nil
			if source != nil {
				modelServices = source.Services
			}
		}
		modelRunning := false
		for _, record := range modelServices {
			if record.Slug == "model" && isCurrent(record) {
				modelRunning = true
				break
			}
		}
		if !modelRunning {
			delete(target.Ports, "model")
		}
	}
	env, err := target.ServiceEnv()
	if err != nil {
		return ServiceRecord{}, nil, err
	}
	sp, err := ResolveService(s.Root, launch, slug, st.Ports, env)
	if err != nil {
		return ServiceRecord{}, nil, err
	}
	args := opts.Args
	if len(args) > 0 && args[0] == "--" {
		args = args[1:]
	}
	if slug == "web" && len(args) > 0 {
		sp.Command = append(sp.Command, "--")
	}
	sp.Command = append(sp.Command, args...)
	if running != nil {
		if running.SpecHash != sp.Hash() {
			return ServiceRecord{}, nil, fmt.Errorf("%s already runs with another configuration; stop it before changing its command or environment", slug)
		}
		return *running, nil, nil
	}
	if err := ctx.Err(); err != nil {
		return ServiceRecord{}, nil, err
	}
	if opts.BeforeStart != nil {
		if err := opts.BeforeStart(ctx, sp); err != nil {
			return ServiceRecord{}, nil, err
		}
	}
	if err := ctx.Err(); err != nil {
		return ServiceRecord{}, nil, err
	}
	for _, previous := range st.Services {
		if previous.Slug == slug && previous.PGID > 0 {
			if left := stopRecords([]ServiceRecord{previous}, opts.StopTimeout); len(left) > 0 {
				return ServiceRecord{}, nil, fmt.Errorf("cannot stop stale %s", slug)
			}
		}
	}
	if err := ctx.Err(); err != nil {
		return ServiceRecord{}, nil, err
	}
	record, done, err := launchService(sp, filepath.Join(s.LogDir(), slug+".log"), opts.IO)
	if err != nil {
		return ServiceRecord{}, nil, err
	}
	merged := make([]ServiceRecord, 0, len(st.Services)+1)
	for _, existing := range st.Services {
		if existing.Slug != slug {
			merged = append(merged, existing)
		}
	}
	st.Services = append(merged, record)
	st.Phase = PhaseReady
	if err := s.WriteState(st); err != nil {
		_ = stopRecords([]ServiceRecord{record}, time.Second)
		return ServiceRecord{}, nil, err
	}
	return record, done, nil
}

func finishService(record ServiceRecord, done <-chan error, sig os.Signal, timeout time.Duration) error {
	rememberGroup(&record)
	if err := signalService(record, sig); err != nil {
		return err
	}
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case err := <-done:
		return err
	case <-timer.C:
		if err := signalService(record, os.Kill); err != nil {
			return err
		}
		select {
		case err := <-done:
			return err
		case <-time.After(4 * time.Second):
			return &serviceCleanupError{record: record}
		}
	}
}

func (s *Stack) recordServiceExit(record ServiceRecord, wait time.Duration) error {
	unlock, err := s.Lock(context.Background(), "record "+record.Slug+" exit", wait)
	if err != nil {
		return err
	}
	defer unlock()
	st, err := s.ReadState()
	if err != nil || st == nil {
		return err
	}
	if st.Root != s.Root || st.Project != s.Project {
		return nil
	}
	anyRunning := false
	matched := false
	for i, current := range st.Services {
		if current.Slug == record.Slug && current.PID == record.PID && current.StartMarker == record.StartMarker {
			matched = true
			if groupAlive(record.PGID) {
				st.Services[i].Members = record.Members
				st.Phase = PhaseFailed
			} else {
				st.Services[i].PID = 0
				st.Services[i].PGID = 0
			}
		}
		anyRunning = anyRunning || isCurrent(st.Services[i]) || groupAlive(st.Services[i].PGID)
	}
	if !matched {
		return nil
	}
	if !anyRunning {
		st.Phase = PhaseStopped
	}
	return s.WriteState(st)
}

func attachService(ctx context.Context, record ServiceRecord, output io.Writer, signals <-chan os.Signal) error {
	logFile, err := os.Open(record.Log)
	if err != nil {
		return err
	}
	defer func() { _ = logFile.Close() }()
	if output == nil {
		output = io.Discard
	}
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		if _, err := io.Copy(output, logFile); err != nil {
			return err
		}
		if !isCurrent(record) {
			return nil
		}
		select {
		case <-ctx.Done():
			return nil
		case <-signals:
			return nil
		case <-ticker.C:
		}
	}
}
