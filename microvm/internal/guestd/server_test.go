package guestd

import (
	"context"
	"errors"
	"io"
	"net"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

var testKey = strings.Repeat("k", 32)

type fakeSys struct {
	mu      sync.Mutex
	clock   []time.Time
	entropy [][]byte
	grown   []string
	minDev  []uint64
	order   []string
	cas     [][]byte
	// If set, SetClock signals inClock and waits for clockGate.
	inClock, clockGate chan struct{}
}

func (f *fakeSys) step(name string) {
	f.order = append(f.order, name)
}

func (f *fakeSys) system() System {
	return System{
		SetClock: func(t time.Time) error {
			if f.clockGate != nil {
				f.inClock <- struct{}{}
				<-f.clockGate
			}
			f.mu.Lock()
			defer f.mu.Unlock()
			f.clock = append(f.clock, t)
			f.step("clock")
			return nil
		},
		AddEntropy: func(b []byte) (bool, error) {
			f.mu.Lock()
			defer f.mu.Unlock()
			f.entropy = append(f.entropy, b)
			f.step("entropy")
			return true, nil
		},
		Attach: func() error {
			f.mu.Lock()
			defer f.mu.Unlock()
			f.step("attach")
			return nil
		},
		ResetRelay: func() (bool, error) {
			f.mu.Lock()
			defer f.mu.Unlock()
			f.step("relay")
			return true, nil
		},
		InstallCA: func(pem []byte) error {
			f.mu.Lock()
			defer f.mu.Unlock()
			f.cas = append(f.cas, pem)
			f.step("ca")
			return nil
		},
		GrowFS: func(mp string, minDev uint64) (uint64, uint64, error) {
			f.mu.Lock()
			defer f.mu.Unlock()
			f.grown = append(f.grown, mp)
			f.minDev = append(f.minDev, minDev)
			f.step("grow")
			return 1 << 30, 2 << 30, nil
		},
	}
}

type harness struct {
	t   *testing.T
	sys *fakeSys
	srv *Server
	lis *bufconn.Listener
}

func newHarness(t *testing.T, ecfg execs.Config, cfg Config) *harness {
	t.Helper()
	return newHarnessWith(t, ecfg, cfg, &fakeSys{})
}

func newHarnessWith(t *testing.T, ecfg execs.Config, cfg Config, sys *fakeSys) *harness {
	t.Helper()
	ecfg.Isolator = execs.ProcessGroups{}
	m, err := execs.NewManager(ecfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	srv, err := NewServer(cfg, sys.system(), m)
	if err != nil {
		t.Fatal(err)
	}
	lis := bufconn.Listen(1 << 20)
	gs := srv.NewGRPCServer()
	go func() { _ = gs.Serve(lis) }()
	t.Cleanup(gs.Stop)
	return &harness{t: t, sys: sys, srv: srv, lis: lis}
}

// client opens a new connection. Close it to drop the client.
func (h *harness) client() (pb.SandboxdClient, *grpc.ClientConn) {
	h.t.Helper()
	conn, err := grpc.NewClient("passthrough:///bufnet",
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) { return h.lis.DialContext(ctx) }),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		h.t.Fatal(err)
	}
	h.t.Cleanup(func() { _ = conn.Close() })
	return pb.NewSandboxdClient(conn), conn
}

func keyed(ctx context.Context) context.Context {
	return metadata.AppendToOutgoingContext(ctx, KeyHeader, testKey)
}

func initReq() *pb.InitRequest {
	return &pb.InitRequest{
		HostTime: timestamppb.New(time.Date(2030, 1, 2, 3, 4, 5, 0, time.UTC)),
		Entropy:  make([]byte, 32), Env: map[string]string{"FROM_INIT": "yes"},
		SessionIds: []string{"s1", "s2"}, Generation: 7, SandboxId: "sb-1", ScratchBytes: 2 << 30,
	}
}

// initialized sets the key (as the node agent does) and runs Init.
func (h *harness) initialized() pb.SandboxdClient {
	h.t.Helper()
	c, _ := h.client()
	if _, err := c.SetKey(context.Background(), &pb.SetKeyRequest{Key: testKey}); err != nil {
		h.t.Fatal(err)
	}
	if _, err := c.Init(keyed(context.Background()), initReq()); err != nil {
		h.t.Fatal(err)
	}
	return c
}

func reason(err error) string {
	st, ok := status.FromError(err)
	if !ok {
		return ""
	}
	for _, d := range st.Details() {
		if info, ok := d.(*errdetails.ErrorInfo); ok {
			return info.GetReason()
		}
	}
	return ""
}

type collected struct {
	id      string
	stdout  string
	stderr  string
	gaps    []*pb.OutputGap
	result  *pb.ExecResult
	started *pb.ExecStarted
}

type eventStream interface {
	Recv() (*pb.ExecEvent, error)
}

func collect(t *testing.T, s eventStream) collected {
	t.Helper()
	var c collected
	var out, errb strings.Builder
	for {
		ev, err := s.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatalf("recv: %v", err)
		}
		switch x := ev.GetEvent().(type) {
		case *pb.ExecEvent_Started:
			c.started, c.id = x.Started, x.Started.GetExecutionId()
		case *pb.ExecEvent_Output:
			if x.Output.GetStream() == pb.OutputStream_STDOUT {
				out.Write(x.Output.GetData())
			} else {
				errb.Write(x.Output.GetData())
			}
		case *pb.ExecEvent_Gap:
			c.gaps = append(c.gaps, x.Gap)
		case *pb.ExecEvent_Result:
			c.result = x.Result
		}
	}
	c.stdout, c.stderr = out.String(), errb.String()
	if c.result == nil {
		t.Fatal("stream ended without a result")
	}
	return c
}

func sh(script string) *pb.Command { return &pb.Command{Argv: []string{"sh", "-c", script}} }

// pidsGone waits until none of the pids exist (they may be zombies for a
// moment before their new parent reaps them).
func pidsGone(t *testing.T, pids []int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for _, p := range pids {
		for syscall.Kill(p, 0) == nil {
			if time.Now().After(deadline) {
				t.Fatalf("pid %d still exists", p)
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
}

func parsePIDs(t *testing.T, s string) []int {
	t.Helper()
	var pids []int
	for _, f := range strings.Fields(s) {
		p, err := strconv.Atoi(f)
		if err != nil {
			t.Fatalf("bad pid %q in %q", f, s)
		}
		pids = append(pids, p)
	}
	return pids
}

func TestInitGateAndKey(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{Version: "test", GrowMounts: []string{"/mnt/scratch"}})
	c, _ := h.client()
	ctx := context.Background()

	hr, err := c.Health(ctx, &pb.HealthRequest{})
	if err != nil || hr.GetInitialized() || hr.GetKeySet() {
		t.Fatalf("health before key: %v %v", hr, err)
	}
	// Before SetKey nothing but Health and SetKey works, Init included.
	if _, err := c.Init(keyed(ctx), initReq()); reason(err) != "KEY_NOT_SET" {
		t.Fatalf("init before key: %v", err)
	}
	if _, err := c.Start(keyed(ctx), &pb.StartRequest{Command: sh("true")}); reason(err) != "KEY_NOT_SET" {
		t.Fatalf("start before key: %v", err)
	}
	if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: "short"}); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("short key: %v", err)
	}
	if r, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: testKey}); err != nil || r.GetAlreadySet() {
		t.Fatalf("set key: %v %v", r, err)
	}
	if r, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: testKey}); err != nil || !r.GetAlreadySet() {
		t.Fatalf("repeat set key: %v %v", r, err)
	}
	other := &pb.SetKeyRequest{Key: strings.Repeat("x", 32)}
	if _, err := c.SetKey(ctx, other); reason(err) != "KEY_ALREADY_SET" || status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("second key: %v", err)
	}
	if _, err := c.Init(ctx, initReq()); reason(err) != "UNAUTHENTICATED" {
		t.Fatalf("init without key: %v", err)
	}
	if _, err := c.Start(keyed(ctx), &pb.StartRequest{Command: sh("true")}); reason(err) != "NOT_INITIALIZED" {
		t.Fatalf("start before init: %v", err)
	}

	before := time.Now()
	resp, err := c.Init(keyed(ctx), initReq())
	if err != nil {
		t.Fatal(err)
	}
	want := time.Date(2030, 1, 2, 3, 4, 5, 0, time.UTC)
	if len(h.sys.clock) != 1 || !h.sys.clock[0].Equal(want) {
		t.Fatalf("clock set to %v, want %v", h.sys.clock, want)
	}
	// The step is the host time minus the guest clock at Init.
	if d := resp.GetClockStep().AsDuration() - want.Sub(before); d > time.Second || d < -time.Second {
		t.Fatalf("clock step %v, want about %v", resp.GetClockStep().AsDuration(), want.Sub(before))
	}
	if len(h.sys.entropy) != 1 || !resp.GetEntropyCredited() {
		t.Fatalf("entropy not added: %v", resp)
	}
	if len(resp.GetGrown()) != 1 || resp.GetGrown()[0].GetMountPoint() != "/mnt/scratch" || resp.GetGrown()[0].GetNewBytes() != 2<<30 {
		t.Fatalf("grown: %v", resp.GetGrown())
	}
	if len(h.sys.minDev) != 1 || h.sys.minDev[0] != 2<<30 {
		t.Fatalf("GrowFS got min device size %v, want scratch_bytes", h.sys.minDev)
	}
	if got := strings.Join(h.sys.order, ","); got != "clock,entropy,attach,grow,relay" || !resp.GetAttached() || !resp.GetRelayReset() {
		t.Fatalf("init steps %q, attached %v, relay_reset %v", got, resp.GetAttached(), resp.GetRelayReset())
	}
	if got := h.srv.SessionIDs(); strings.Join(got, ",") != "s1,s2" {
		t.Fatalf("sessions %v", got)
	}

	hr, _ = c.Health(ctx, &pb.HealthRequest{})
	if !hr.GetInitialized() || !hr.GetKeySet() || hr.GetGeneration() != 7 || hr.GetSandboxId() != "sb-1" {
		t.Fatalf("health after init: %v", hr)
	}
	if _, err := c.Start(ctx, &pb.StartRequest{Command: sh("true")}); reason(err) != "UNAUTHENTICATED" {
		t.Fatalf("no key: %v", err)
	}
	wrong := metadata.AppendToOutgoingContext(ctx, KeyHeader, strings.Repeat("x", 32))
	if _, err := c.Start(wrong, &pb.StartRequest{Command: sh("true")}); reason(err) != "UNAUTHENTICATED" {
		t.Fatalf("wrong key: %v", err)
	}
	if _, err := c.Init(keyed(ctx), initReq()); err != nil {
		t.Fatalf("re-init with key: %v", err)
	}
	if _, err := c.Start(keyed(ctx), &pb.StartRequest{Command: sh("true")}); err != nil {
		t.Fatalf("start after init: %v", err)
	}
}

// The agent sends the egress CA with SetKey; Init installs it after attach
// and grow, before the relay reset. A later SetKey with the same key can
// replace the CA; one without a CA keeps it.
func TestEgressCA(t *testing.T) {
	state := filepath.Join(t.TempDir(), "init.json")
	h := newHarness(t, execs.Config{}, Config{StateFile: state, GrowMounts: []string{"/mnt/scratch"}})
	c, _ := h.client()
	ctx := context.Background()
	ca1, err := testcerts.NewCA("egress one")
	if err != nil {
		t.Fatal(err)
	}
	ca2, err := testcerts.NewCA("egress two")
	if err != nil {
		t.Fatal(err)
	}
	leaf, _, err := ca1.Leaf("server", true)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: testKey, EgressCaPem: leaf}); reason(err) != "INVALID_ARGUMENT" {
		t.Fatalf("leaf as CA: %v", err)
	}
	if hr, _ := c.Health(ctx, &pb.HealthRequest{}); hr.GetKeySet() {
		t.Fatal("key set by a refused SetKey")
	}
	if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: testKey, EgressCaPem: ca1.PEM}); err != nil {
		t.Fatal(err)
	}
	resp, err := c.Init(keyed(ctx), initReq())
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(h.sys.order, ","); got != "clock,entropy,attach,grow,ca,relay" || !resp.GetEgressCaInstalled() {
		t.Fatalf("init steps %q, egress_ca_installed %v", got, resp.GetEgressCaInstalled())
	}
	if len(h.sys.cas) != 1 || string(h.sys.cas[0]) != string(ca1.PEM) {
		t.Fatalf("installed %q", h.sys.cas)
	}
	// A new CA with the same key (a later Create after a CA rotation).
	if r, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: testKey, EgressCaPem: ca2.PEM}); err != nil || !r.GetAlreadySet() {
		t.Fatalf("new CA: %v %v", r, err)
	}
	if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: testKey}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Init(keyed(ctx), initReq()); err != nil {
		t.Fatal(err)
	}
	if len(h.sys.cas) != 2 || string(h.sys.cas[1]) != string(ca2.PEM) {
		t.Fatalf("second install %d CAs", len(h.sys.cas))
	}
	// A restarted daemon keeps the CA for the next Init.
	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	sys2 := &fakeSys{}
	srv, err := NewServer(Config{StateFile: state}, sys2.system(), m)
	if err != nil {
		t.Fatal(err)
	}
	in := metadata.NewIncomingContext(ctx, metadata.Pairs(KeyHeader, testKey))
	if _, err := srv.Init(in, initReq()); err != nil {
		t.Fatal(err)
	}
	if len(sys2.cas) != 1 || string(sys2.cas[0]) != string(ca2.PEM) {
		t.Fatalf("after restart: %d CAs", len(sys2.cas))
	}
	// A failed install fails Init.
	h.srv.sys.InstallCA = func([]byte) error { return errors.New("read-only file system") }
	if _, err := c.Init(keyed(ctx), initReq()); reason(err) != "INIT_FAILED" {
		t.Fatalf("failed install: %v", err)
	}
}

func TestInitFailsWhenGrowFails(t *testing.T) {
	sys := &fakeSys{}
	h := newHarnessWith(t, execs.Config{}, Config{GrowMounts: []string{"/mnt/scratch"}}, sys)
	h.srv.sys.GrowFS = func(string, uint64) (uint64, uint64, error) {
		return 0, 0, errors.New("device is 1073741824 bytes, want at least 2147483648")
	}
	c, _ := h.client()
	if _, err := c.SetKey(context.Background(), &pb.SetKeyRequest{Key: testKey}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Init(keyed(context.Background()), initReq()); reason(err) != "INIT_FAILED" {
		t.Fatalf("init with a small device: %v", err)
	}
	if hr, _ := c.Health(context.Background(), &pb.HealthRequest{}); hr.GetInitialized() {
		t.Fatal("initialized after a failed Init")
	}
}

// Concurrent SetKey calls with different keys: exactly one key stays.
func TestSetKeyFirstWins(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	c, _ := h.client()
	const n = 16
	errs := make([]error, n)
	var wg sync.WaitGroup
	for i := range n {
		wg.Go(func() {
			_, errs[i] = c.SetKey(context.Background(), &pb.SetKeyRequest{Key: strings.Repeat(strconv.Itoa(i%10), 32) + strconv.Itoa(i)})
		})
	}
	wg.Wait()
	won := -1
	for i, err := range errs {
		switch {
		case err == nil:
			if won >= 0 {
				t.Fatalf("keys %d and %d both set", won, i)
			}
			won = i
		case reason(err) != "KEY_ALREADY_SET":
			t.Fatalf("key %d: %v", i, err)
		}
	}
	if won < 0 {
		t.Fatal("no key set")
	}
	key := strings.Repeat(strconv.Itoa(won%10), 32) + strconv.Itoa(won)
	ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs(KeyHeader, key))
	if err := h.srv.check(ctx, pb.Sandboxd_Init_FullMethodName); err != nil {
		t.Fatalf("winning key: %v", err)
	}
}

func TestSetKeyRejectsKeyThatMetadataCannotCarry(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	c, _ := h.client()
	for _, key := range []string{strings.Repeat("k", 31) + " ", strings.Repeat("k", 31) + "\x01", strings.Repeat("é", 16), strings.Repeat("k", 513)} {
		if _, err := c.SetKey(context.Background(), &pb.SetKeyRequest{Key: key}); reason(err) != "INVALID_ARGUMENT" {
			t.Fatalf("key %q: %v", key, err)
		}
	}
}

func TestContextErrorHasErrorInfo(t *testing.T) {
	for _, in := range []error{context.Canceled, context.DeadlineExceeded} {
		err := execError(in)
		st, _ := status.FromError(err)
		if st.Code() != status.FromContextError(in).Code() || reason(err) != "INTERNAL" {
			t.Fatalf("%v: code %v reason %q", in, st.Code(), reason(err))
		}
	}
}

func TestInitStateSurvivesRestart(t *testing.T) {
	state := filepath.Join(t.TempDir(), "run", "init.json")
	h := newHarness(t, execs.Config{}, Config{StateFile: state})
	h.initialized()

	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	srv, err := NewServer(Config{StateFile: state}, (&fakeSys{}).system(), m)
	if err != nil {
		t.Fatal(err)
	}
	if err := srv.check(context.Background(), pb.Sandboxd_Start_FullMethodName); reason(err) != "UNAUTHENTICATED" {
		t.Fatalf("restarted daemon without key: %v", err)
	}
	if _, err := srv.SetKey(context.Background(), &pb.SetKeyRequest{Key: strings.Repeat("x", 32)}); reason(err) != "KEY_ALREADY_SET" {
		t.Fatalf("restarted daemon took a new key: %v", err)
	}
	ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs(KeyHeader, testKey))
	if err := srv.check(ctx, pb.Sandboxd_Start_FullMethodName); err != nil {
		t.Fatalf("restarted daemon with key: %v", err)
	}
}

func TestRunTypedResult(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())

	s, err := c.Run(ctx, &pb.RunRequest{Command: &pb.Command{
		Argv: []string{"sh", "-c", `echo "out $FROM_INIT $PER_CALL"; echo err >&2; exit 3`},
		Env:  map[string]string{"PER_CALL": "call"}, Labels: map[string]string{"session_id": "s1"},
	}})
	if err != nil {
		t.Fatal(err)
	}
	r := collect(t, s)
	if r.started == nil || r.id == "" || r.started.GetPid() <= 0 {
		t.Fatalf("no started event: %+v", r)
	}
	if r.stdout != "out yes call\n" || r.stderr != "err\n" {
		t.Fatalf("output %q / %q", r.stdout, r.stderr)
	}
	if r.result.GetCompletion() != pb.Completion_EXITED || r.result.GetExitCode() != 3 {
		t.Fatalf("result %v", r.result)
	}
	if r.result.GetStdoutBytes() != int64(len(r.stdout)) || r.result.GetStderrBytes() != 4 {
		t.Fatalf("byte counts %v", r.result)
	}
	// Default deadline is 30 min.
	if d := r.started.GetDeadlineAt().AsTime().Sub(r.started.GetStartedAt().AsTime()); d != 30*time.Minute {
		t.Fatalf("default deadline %v", d)
	}

	ins, err := c.Inspect(ctx, &pb.InspectRequest{ExecutionId: r.id})
	if err != nil {
		t.Fatal(err)
	}
	if ins.GetExecution().GetState() != pb.ExecState_ENDED || ins.GetExecution().GetResult().GetExitCode() != 3 {
		t.Fatalf("inspect %v", ins)
	}
	l, err := c.List(ctx, &pb.ListRequest{Labels: map[string]string{"session_id": "s1"}})
	if err != nil || len(l.GetExecutions()) != 1 {
		t.Fatalf("list by label: %v %v", l, err)
	}
	l, _ = c.List(ctx, &pb.ListRequest{Labels: map[string]string{"session_id": "other"}})
	if len(l.GetExecutions()) != 0 {
		t.Fatalf("list other label: %v", l)
	}

	// A command killed by a signal it did not get from the daemon.
	s, _ = c.Run(ctx, &pb.RunRequest{Command: sh("kill -TERM $$")})
	if r := collect(t, s); r.result.GetCompletion() != pb.Completion_SIGNALED || r.result.GetSignal() != int32(syscall.SIGTERM) || r.result.GetExitCode() != -1 {
		t.Fatalf("signaled result %v", r.result)
	}
}

func TestErrors(t *testing.T) {
	h := newHarness(t, execs.Config{MaxDeadline: time.Hour}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())
	if _, err := c.Start(ctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"/no/such/program"}}}); reason(err) != "START_FAILED" {
		t.Fatalf("missing program: %v", err)
	}
	// The program is looked up in the command's PATH.
	noPath := &pb.Command{Argv: []string{"sh", "-c", "true"}, Env: map[string]string{"PATH": "/nonexistent"}}
	if _, err := c.Start(ctx, &pb.StartRequest{Command: noPath}); reason(err) != "START_FAILED" {
		t.Fatalf("PATH from the command env: %v", err)
	}
	if _, err := c.Start(ctx, &pb.StartRequest{Command: &pb.Command{}}); reason(err) != "INVALID_ARGUMENT" {
		t.Fatalf("empty argv: %v", err)
	}
	cmd := sh("true")
	cmd.Deadline = durationpb.New(2 * time.Hour)
	if _, err := c.Start(ctx, &pb.StartRequest{Command: cmd}); reason(err) != "INVALID_ARGUMENT" {
		t.Fatalf("deadline above max: %v", err)
	}
	if _, err := c.Inspect(ctx, &pb.InspectRequest{ExecutionId: "nope"}); reason(err) != "EXECUTION_NOT_FOUND" {
		t.Fatalf("unknown id: %v", err)
	}
	if _, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{}); status.Code(err) != codes.Unimplemented {
		t.Fatalf("reserved call: %v", err)
	}
}

func TestInteract(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())

	st, err := c.Start(ctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"cat"}, Stdin: true}})
	if err != nil {
		t.Fatal(err)
	}
	id := st.GetStarted().GetExecutionId()
	if _, err := c.Interact(ctx, &pb.InteractRequest{ExecutionId: id, Data: []byte("hello ")}); err != nil {
		t.Fatal(err)
	}
	if r, err := c.Interact(ctx, &pb.InteractRequest{ExecutionId: id, Data: []byte("world\n"), CloseStdin: true}); err != nil || r.GetWritten() != 6 {
		t.Fatalf("interact: %v %v", r, err)
	}
	s, _ := c.Stream(ctx, &pb.StreamRequest{ExecutionId: id})
	r := collect(t, s)
	if r.stdout != "hello world\n" || r.result.GetCompletion() != pb.Completion_EXITED || r.result.GetExitCode() != 0 {
		t.Fatalf("cat: %q %v", r.stdout, r.result)
	}
	if _, err := c.Interact(ctx, &pb.InteractRequest{ExecutionId: id, Data: []byte("x")}); reason(err) != "EXECUTION_ENDED" {
		t.Fatalf("interact after end: %v", err)
	}

	st, _ = c.Start(ctx, &pb.StartRequest{Command: sh("sleep 5")})
	if _, err := c.Interact(ctx, &pb.InteractRequest{ExecutionId: st.GetStarted().GetExecutionId(), Data: []byte("x")}); reason(err) != "STDIN_NOT_OPEN" {
		t.Fatalf("interact without stdin: %v", err)
	}
}

func TestCancelKillsTree(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())

	s, err := c.Run(ctx, &pb.RunRequest{Command: sh(`sleep 100 & echo $!; sleep 100 & echo $!; wait`)})
	if err != nil {
		t.Fatal(err)
	}
	ev, _ := s.Recv()
	id := ev.GetStarted().GetExecutionId()
	var out strings.Builder
	for strings.Count(out.String(), "\n") < 2 {
		ev, err := s.Recv()
		if err != nil {
			t.Fatal(err)
		}
		out.Write(ev.GetOutput().GetData())
	}
	pids := parsePIDs(t, out.String())

	start := time.Now()
	cr, err := c.Cancel(ctx, &pb.CancelRequest{ExecutionId: id})
	if err != nil {
		t.Fatalf("cancel is not an error: %v", err)
	}
	if cr.GetResult().GetCompletion() != pb.Completion_CANCELED || cr.GetAlreadyEnded() {
		t.Fatalf("cancel result %v", cr)
	}
	t.Logf("cancel took %v", time.Since(start))
	pidsGone(t, pids)
	// The open Run stream also ends with the CANCELED result.
	if r := collect(t, s); r.result.GetCompletion() != pb.Completion_CANCELED {
		t.Fatalf("run stream result %v", r.result)
	}
	cr, err = c.Cancel(ctx, &pb.CancelRequest{ExecutionId: id})
	if err != nil || !cr.GetAlreadyEnded() || cr.GetResult().GetCompletion() != pb.Completion_CANCELED {
		t.Fatalf("second cancel: %v %v", cr, err)
	}
}

func TestDeadlineKillsTree(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())

	cmd := sh(`sleep 100 & echo $!; wait`)
	cmd.Deadline = durationpb.New(300 * time.Millisecond)
	start := time.Now()
	s, err := c.Run(ctx, &pb.RunRequest{Command: cmd})
	if err != nil {
		t.Fatal(err)
	}
	r := collect(t, s)
	took := time.Since(start)
	if r.result.GetCompletion() != pb.Completion_DEADLINE_EXCEEDED {
		t.Fatalf("result %v", r.result)
	}
	if took < 300*time.Millisecond || took > 3*time.Second {
		t.Fatalf("deadline result after %v", took)
	}
	if d := r.started.GetDeadlineAt().AsTime().Sub(r.started.GetStartedAt().AsTime()); d != 300*time.Millisecond {
		t.Fatalf("deadline_at - started_at = %v", d)
	}
	pidsGone(t, parsePIDs(t, r.stdout))
}

func TestRecordSurvivesDisconnect(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	h.initialized()
	c1, conn1 := h.client()
	ctx := keyed(context.Background())

	s, err := c1.Run(ctx, &pb.RunRequest{Command: sh(`echo one; sleep 0.5; echo two; exit 4`)})
	if err != nil {
		t.Fatal(err)
	}
	ev, err := s.Recv()
	if err != nil {
		t.Fatal(err)
	}
	id := ev.GetStarted().GetExecutionId()
	// Drop the client while the command runs.
	_ = conn1.Close()

	c2, _ := h.client()
	ins, err := c2.Inspect(ctx, &pb.InspectRequest{ExecutionId: id})
	if err != nil || ins.GetExecution().GetState() != pb.ExecState_RUNNING {
		t.Fatalf("inspect after drop: %v %v", ins, err)
	}
	s2, err := c2.Stream(ctx, &pb.StreamRequest{ExecutionId: id})
	if err != nil {
		t.Fatal(err)
	}
	r := collect(t, s2)
	if r.stdout != "one\ntwo\n" || r.result.GetCompletion() != pb.Completion_EXITED || r.result.GetExitCode() != 4 {
		t.Fatalf("after reconnect: %q %v", r.stdout, r.result)
	}
	// Resume from an offset.
	s3, _ := c2.Stream(ctx, &pb.StreamRequest{ExecutionId: id, StdoutOffset: 4})
	if r := collect(t, s3); r.stdout != "two\n" {
		t.Fatalf("from offset 4: %q", r.stdout)
	}
}

func TestOutputGap(t *testing.T) {
	h := newHarness(t, execs.Config{OutputBytes: 16}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())

	st, err := c.Start(ctx, &pb.StartRequest{Command: sh(`printf '%050d' 0; printf END`)})
	if err != nil {
		t.Fatal(err)
	}
	id := st.GetStarted().GetExecutionId()
	// A live stream can attach between the two writes; replay after the end.
	first, _ := c.Stream(ctx, &pb.StreamRequest{ExecutionId: id})
	collect(t, first)
	s, _ := c.Stream(ctx, &pb.StreamRequest{ExecutionId: id})
	r := collect(t, s)
	if r.result.GetStdoutBytes() != 53 {
		t.Fatalf("stdout bytes %d", r.result.GetStdoutBytes())
	}
	if len(r.gaps) != 1 || r.gaps[0].GetFrom() != 0 || r.gaps[0].GetTo() != 37 {
		t.Fatalf("gaps %v", r.gaps)
	}
	if len(r.stdout) != 16 || !strings.HasSuffix(r.stdout, "END") {
		t.Fatalf("kept %q", r.stdout)
	}
}
