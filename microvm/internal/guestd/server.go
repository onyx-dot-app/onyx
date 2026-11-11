// Package guestd serves the Sandboxd gRPC API of the guest daemon (ENG-4571).
package guestd

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// System holds the guest system calls of Init. Tests replace them. A nil
// Attach, ResetRelay or InstallCA is skipped.
type System struct {
	SetClock   func(time.Time) error
	AddEntropy func([]byte) (credited bool, err error)
	// Attach mounts the per-VM drives (idempotent).
	Attach func() error
	// GrowFS fails if the device stays smaller than minDevBytes.
	GrowFS func(mountPoint string, minDevBytes uint64) (oldBytes, newBytes uint64, err error)
	// ResetRelay makes the in-guest egress relay reset its connections. It
	// reports false if the relay is not running.
	ResetRelay func() (bool, error)
	// InstallCA puts the egress CA (PEM) into the guest trust stores. It
	// runs after Attach, so it writes to the overlays. Nil: skipped.
	InstallCA func(pem []byte) error
}

// Config configures a Server.
type Config struct {
	Version string
	// GrowMounts are the ext4 mount points that Init grows to their device
	// size (the scratch disk can grow at Create).
	GrowMounts []string
	// StateFile keeps the Init state across daemon restarts (tmpfs). Empty
	// means memory only.
	StateFile string
	// BaseEnv is the env of every command, before the Init and command env.
	BaseEnv map[string]string
	// Managed configures ManagedStatus and MountManaged. Nil: they fail.
	Managed *ManagedConfig
	// Reclaimer drops the guest page cache when the VM is idle. Nil: off.
	Reclaimer *Reclaimer
	// Files serves the file calls and session saves. Nil means a store
	// with the defaults (files.Config{}).
	Files *files.Store
	// Forwards serves the SetKey dial ports. Nil: no port is forwarded.
	Forwards *Forwards
	Log      *slog.Logger
}

// DefaultBaseEnv is the command env before Init adds to it.
var DefaultBaseEnv = map[string]string{
	"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
	"HOME": "/root",
	"LANG": "C.UTF-8",
}

type initState struct {
	Initialized   bool              `json:"initialized"`
	Key           string            `json:"key"`
	Env           map[string]string `json:"env"`
	SessionIDs    []string          `json:"session_ids"`
	Generation    uint64            `json:"generation"`
	SandboxID     string            `json:"sandbox_id"`
	InitializedAt time.Time         `json:"initialized_at"`
	// EgressCA is the PEM of the last SetKey egress CA.
	EgressCA []byte `json:"egress_ca,omitempty"`
	// DialPorts are the forwarded ports of the last SetKey.
	DialPorts []uint32 `json:"dial_ports,omitempty"`
}

// Server implements pb.SandboxdServer.
type Server struct {
	pb.UnimplementedSandboxdServer
	cfg     Config
	sys     System
	m       *execs.Manager
	files   *files.Store
	started time.Time

	initMu    sync.Mutex // one Init at a time
	managedMu sync.Mutex // one managed drive change at a time
	mu        sync.Mutex
	state     initState
}

// NewServer returns a Server. It loads the Init state from cfg.StateFile.
func NewServer(cfg Config, sys System, m *execs.Manager) (*Server, error) {
	if cfg.Log == nil {
		cfg.Log = slog.Default()
	}
	if cfg.BaseEnv == nil {
		cfg.BaseEnv = DefaultBaseEnv
	}
	if cfg.Files == nil {
		fs, err := files.New(files.Config{})
		if err != nil {
			return nil, err
		}
		cfg.Files = fs
	}
	s := &Server{cfg: cfg, sys: sys, m: m, files: cfg.Files, started: time.Now()}
	if cfg.StateFile != "" {
		raw, err := os.ReadFile(cfg.StateFile)
		switch {
		case err == nil:
			if err := json.Unmarshal(raw, &s.state); err != nil {
				return nil, fmt.Errorf("read %s: %w", cfg.StateFile, err)
			}
		case !os.IsNotExist(err):
			return nil, err
		}
	}
	// A restarted daemon forwards the ports of the key it kept.
	if s.state.Key != "" && cfg.Forwards != nil {
		ports := s.state.DialPorts
		if len(ports) == 0 {
			ports = DefaultDialPorts
		}
		if _, err := cfg.Forwards.Set(ports); err != nil {
			cfg.Log.Warn("dial ports not all forwarded after restart", "err", err)
		}
	}
	return s, nil
}

// Health implements pb.SandboxdServer.
func (s *Server) Health(context.Context, *pb.HealthRequest) (*pb.HealthResponse, error) {
	s.mu.Lock()
	st := s.state
	s.mu.Unlock()
	r := &pb.HealthResponse{
		Initialized: st.Initialized, Version: s.cfg.Version, GuestTime: timestamppb.Now(),
		Generation: st.Generation, SandboxId: st.SandboxID, RunningExecutions: uint32(s.m.Running()),
		Uptime: durationpb.New(time.Since(s.started)), KeySet: st.Key != "", DialPorts: s.cfg.Forwards.Ports(),
	}
	if st.Initialized {
		r.InitializedAt = timestamppb.New(st.InitializedAt)
	}
	return r, nil
}

const (
	minEntropy, maxEntropy = 32, 4096
	minKey, maxKey         = 32, 512
	maxSessions            = 1000
)

func validateInit(r *pb.InitRequest) error {
	if r.GetHostTime() == nil || r.GetHostTime().CheckValid() != nil {
		return fmt.Errorf("host_time is required")
	}
	if n := len(r.GetEntropy()); n < minEntropy || n > maxEntropy {
		return fmt.Errorf("entropy must be %d to %d bytes, got %d", minEntropy, maxEntropy, n)
	}
	if err := validateEnv(r.GetEnv()); err != nil {
		return err
	}
	if len(r.GetSessionIds()) > maxSessions {
		return fmt.Errorf("at most %d session_ids", maxSessions)
	}
	for _, id := range r.GetSessionIds() {
		if id == "" || len(id) > 128 || strings.ContainsAny(id, "/\x00") || id == "." || id == ".." {
			return fmt.Errorf("bad session id %q", id)
		}
	}
	return nil
}

func validateEnv(env map[string]string) error {
	for k, v := range env {
		if k == "" || strings.ContainsAny(k, "=\x00") || strings.ContainsRune(v, 0) {
			return fmt.Errorf("bad env name or value %q", k)
		}
	}
	return nil
}

// Init implements pb.SandboxdServer.
func (s *Server) Init(_ context.Context, r *pb.InitRequest) (*pb.InitResponse, error) {
	if err := validateInit(r); err != nil {
		return nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "%v", err)
	}
	s.initMu.Lock()
	defer s.initMu.Unlock()

	host := r.GetHostTime().AsTime()
	before := time.Now()
	if err := s.sys.SetClock(host); err != nil {
		return nil, apiError(pb.ErrorReason_INIT_FAILED, "set clock: %v", err)
	}
	step := host.Sub(before)
	credited, err := s.sys.AddEntropy(r.GetEntropy())
	if err != nil {
		return nil, apiError(pb.ErrorReason_INIT_FAILED, "add entropy: %v", err)
	}
	resp := &pb.InitResponse{ClockStep: durationpb.New(step), EntropyCredited: credited, Version: s.cfg.Version}
	if s.sys.Attach != nil {
		if err := s.sys.Attach(); err != nil {
			return nil, apiError(pb.ErrorReason_INIT_FAILED, "attach drives: %v", err)
		}
		resp.Attached = true
	}
	for _, mp := range s.cfg.GrowMounts {
		oldB, newB, err := s.sys.GrowFS(mp, r.GetScratchBytes())
		if err != nil {
			return nil, apiError(pb.ErrorReason_INIT_FAILED, "grow %s: %v", mp, err)
		}
		resp.Grown = append(resp.Grown, &pb.GrownFS{MountPoint: mp, OldBytes: oldB, NewBytes: newB})
	}
	s.mu.Lock()
	caPEM := s.state.EgressCA
	s.mu.Unlock()
	if len(caPEM) > 0 && s.sys.InstallCA != nil {
		if err := s.sys.InstallCA(caPEM); err != nil {
			return nil, apiError(pb.ErrorReason_INIT_FAILED, "install egress CA: %v", err)
		}
		resp.EgressCaInstalled = true
	}
	if s.sys.ResetRelay != nil {
		reset, err := s.sys.ResetRelay()
		if err != nil {
			return nil, apiError(pb.ErrorReason_INIT_FAILED, "reset egress relay: %v", err)
		}
		resp.RelayReset = reset
	}

	s.mu.Lock()
	key := s.state.Key
	s.mu.Unlock()
	st := initState{
		Initialized: true, Key: key, Env: maps.Clone(r.GetEnv()), SessionIDs: slices.Clone(r.GetSessionIds()),
		Generation: r.GetGeneration(), SandboxID: r.GetSandboxId(), InitializedAt: time.Now(), EgressCA: caPEM,
	}
	s.mu.Lock()
	st.DialPorts = s.state.DialPorts
	s.mu.Unlock()
	if err := s.saveState(st); err != nil {
		return nil, apiError(pb.ErrorReason_INIT_FAILED, "save state: %v", err)
	}
	s.mu.Lock()
	s.state = st
	s.mu.Unlock()
	s.cfg.Log.Info("init", "sandbox_id", st.SandboxID, "generation", st.Generation,
		"clock_step", step, "entropy_credited", credited, "attached", resp.Attached, "egress_ca", resp.EgressCaInstalled, "relay_reset", resp.RelayReset,
		"sessions", len(st.SessionIDs))
	return resp, nil
}

func (s *Server) saveState(st initState) error {
	if s.cfg.StateFile == "" {
		return nil
	}
	raw, err := json.Marshal(st)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(s.cfg.StateFile), 0o700); err != nil {
		return err
	}
	tmp := s.cfg.StateFile + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, s.cfg.StateFile)
}

// SessionIDs returns the session list from the last Init.
func (s *Server) SessionIDs() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return slices.Clone(s.state.SessionIDs)
}

func (s *Server) spec(c *pb.Command) (execs.Spec, error) {
	if c == nil {
		return execs.Spec{}, apiError(pb.ErrorReason_INVALID_ARGUMENT, "command is required")
	}
	if err := validateEnv(c.GetEnv()); err != nil {
		return execs.Spec{}, apiError(pb.ErrorReason_INVALID_ARGUMENT, "%v", err)
	}
	env := maps.Clone(s.cfg.BaseEnv)
	s.mu.Lock()
	maps.Copy(env, s.state.Env)
	s.mu.Unlock()
	maps.Copy(env, c.GetEnv())
	list := make([]string, 0, len(env))
	for _, k := range slices.Sorted(maps.Keys(env)) {
		list = append(list, k+"="+env[k])
	}
	var deadline time.Duration
	if d := c.GetDeadline(); d != nil {
		if err := d.CheckValid(); err != nil {
			return execs.Spec{}, apiError(pb.ErrorReason_INVALID_ARGUMENT, "deadline: %v", err)
		}
		deadline = d.AsDuration()
	}
	return execs.Spec{
		Argv: c.GetArgv(), Dir: c.GetCwd(), Env: list, Stdin: c.GetStdin(),
		Deadline: deadline, Labels: c.GetLabels(),
	}, nil
}

func (s *Server) start(c *pb.Command) (*execs.Execution, error) {
	spec, err := s.spec(c)
	if err != nil {
		return nil, err
	}
	e, err := s.m.Start(spec)
	if err != nil {
		return nil, execError(err)
	}
	return e, nil
}

func startedEvent(e *execs.Execution) *pb.ExecStarted {
	return &pb.ExecStarted{
		ExecutionId: e.ID, Pid: int32(e.PID),
		StartedAt: timestamppb.New(e.StartedAt), DeadlineAt: timestamppb.New(e.DeadlineAt),
	}
}

// Run implements pb.SandboxdServer.
func (s *Server) Run(r *pb.RunRequest, stream pb.Sandboxd_RunServer) error {
	e, err := s.start(r.GetCommand())
	if err != nil {
		return err
	}
	if err := stream.Send(&pb.ExecEvent{Event: &pb.ExecEvent_Started{Started: startedEvent(e)}}); err != nil {
		return err
	}
	return sendOutput(stream.Context(), e, [2]int64{}, stream.Send)
}

// Start implements pb.SandboxdServer.
func (s *Server) Start(_ context.Context, r *pb.StartRequest) (*pb.StartResponse, error) {
	e, err := s.start(r.GetCommand())
	if err != nil {
		return nil, err
	}
	return &pb.StartResponse{Started: startedEvent(e)}, nil
}

// Stream implements pb.SandboxdServer.
func (s *Server) Stream(r *pb.StreamRequest, stream pb.Sandboxd_StreamServer) error {
	if r.GetStdoutOffset() < 0 || r.GetStderrOffset() < 0 {
		return apiError(pb.ErrorReason_INVALID_ARGUMENT, "offsets must not be negative")
	}
	e, err := s.m.Get(r.GetExecutionId())
	if err != nil {
		return execError(err)
	}
	return sendOutput(stream.Context(), e, [2]int64{r.GetStdoutOffset(), r.GetStderrOffset()}, stream.Send)
}

const chunkBytes = 64 << 10

var protoStream = [2]pb.OutputStream{pb.OutputStream_STDOUT, pb.OutputStream_STDERR}

// sendOutput sends output from off until the execution ends, then the result.
func sendOutput(ctx context.Context, e *execs.Execution, off [2]int64, send func(*pb.ExecEvent) error) error {
	for {
		changed := e.Changed()
		// Read the end state first: after the end the output is final, so
		// this pass drains it.
		res, ended := e.Ended()
		for i := range off {
			for {
				data, gapTo, next := e.Read(execs.Stream(i), off[i], chunkBytes)
				if gapTo > off[i] {
					gap := &pb.OutputGap{Stream: protoStream[i], From: off[i], To: gapTo}
					if err := send(&pb.ExecEvent{Event: &pb.ExecEvent_Gap{Gap: gap}}); err != nil {
						return err
					}
					off[i] = gapTo
				}
				if len(data) == 0 {
					off[i] = next
					break
				}
				out := &pb.OutputChunk{Stream: protoStream[i], Offset: off[i], Data: data}
				if err := send(&pb.ExecEvent{Event: &pb.ExecEvent_Output{Output: out}}); err != nil {
					return err
				}
				off[i] = next
			}
		}
		if ended {
			return send(&pb.ExecEvent{Event: &pb.ExecEvent_Result{Result: toResult(res)}})
		}
		select {
		case <-changed:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// Interact implements pb.SandboxdServer.
func (s *Server) Interact(_ context.Context, r *pb.InteractRequest) (*pb.InteractResponse, error) {
	e, err := s.m.Get(r.GetExecutionId())
	if err != nil {
		return nil, execError(err)
	}
	n, err := e.WriteStdin(r.GetData(), r.GetCloseStdin())
	if err != nil {
		return &pb.InteractResponse{Written: int64(n)}, execError(err)
	}
	return &pb.InteractResponse{Written: int64(n)}, nil
}

// Cancel implements pb.SandboxdServer.
func (s *Server) Cancel(ctx context.Context, r *pb.CancelRequest) (*pb.CancelResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	res, already, err := s.m.Cancel(ctx, r.GetExecutionId())
	if err != nil {
		return nil, execError(err)
	}
	return &pb.CancelResponse{Result: toResult(res), AlreadyEnded: already}, nil
}

// Inspect implements pb.SandboxdServer.
func (s *Server) Inspect(_ context.Context, r *pb.InspectRequest) (*pb.InspectResponse, error) {
	e, err := s.m.Get(r.GetExecutionId())
	if err != nil {
		return nil, execError(err)
	}
	return &pb.InspectResponse{Execution: toExecution(e.Info())}, nil
}

// List implements pb.SandboxdServer.
func (s *Server) List(_ context.Context, r *pb.ListRequest) (*pb.ListResponse, error) {
	out := &pb.ListResponse{}
	for _, e := range s.m.List(r.GetLabels()) {
		out.Executions = append(out.Executions, toExecution(e.Info()))
	}
	return out, nil
}

var completions = map[execs.Completion]pb.Completion{
	execs.Exited:           pb.Completion_EXITED,
	execs.Signaled:         pb.Completion_SIGNALED,
	execs.Canceled:         pb.Completion_CANCELED,
	execs.DeadlineExceeded: pb.Completion_DEADLINE_EXCEEDED,
}

func toResult(r execs.Result) *pb.ExecResult {
	return &pb.ExecResult{
		Completion: completions[r.Completion], ExitCode: int32(r.ExitCode), Signal: int32(r.Signal),
		FinishedAt: timestamppb.New(r.FinishedAt), StdoutBytes: r.Bytes[0], StderrBytes: r.Bytes[1],
	}
}

func toExecution(i execs.Info) *pb.Execution {
	x := &pb.Execution{
		ExecutionId: i.ID, State: pb.ExecState_RUNNING, Argv: i.Argv, Labels: i.Labels, Pid: int32(i.PID),
		StartedAt: timestamppb.New(i.StartedAt), DeadlineAt: timestamppb.New(i.DeadlineAt),
		StdoutBytes: i.Bytes[0], StderrBytes: i.Bytes[1],
	}
	if i.Ended {
		x.State, x.Result = pb.ExecState_ENDED, toResult(i.Result)
	}
	return x
}
