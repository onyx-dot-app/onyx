package server

import (
	"bufio"
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/egressca"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/metrics"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	"github.com/onyx-dot-app/onyx/microvm/internal/transfer"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const (
	sandbox2 = "22222222-2222-4222-8222-222222222222"
	vmKey    = "kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk"
)

// chanListener hands accepted vsock streams to a gRPC server.
type chanListener struct {
	ch     chan net.Conn
	done   chan struct{}
	closed sync.Once
}

func (l *chanListener) Accept() (net.Conn, error) {
	select {
	case c := <-l.ch:
		return c, nil
	case <-l.done:
		return nil, net.ErrClosed
	}
}
func (l *chanListener) Close() error   { l.closed.Do(func() { close(l.done) }); return nil }
func (l *chanListener) Addr() net.Addr { return &net.UnixAddr{Name: "vsock", Net: "unix"} }

type readConn struct {
	net.Conn
	r *bufio.Reader
}

func (c *readConn) Read(p []byte) (int, error) { return c.r.Read(p) }

// fakeVM is a Firecracker vsock UDS with a real guest daemon behind port 52.
type fakeVM struct {
	uds      string
	connects atomic.Int32
	// cas are the egress CAs that Init installed.
	casMu sync.Mutex
	cas   [][]byte
}

func startFakeVM(t *testing.T) *fakeVM {
	t.Helper()
	return startFakeVMWith(t, guestd.Config{Version: "test"})
}

// startFakeVMFiles starts a fake VM whose daemon serves fs (nil: defaults).
func startFakeVMFiles(t *testing.T, fs *files.Store) *fakeVM {
	t.Helper()
	return startFakeVMWith(t, guestd.Config{Version: "test", Files: fs})
}

func startFakeVMWith(t *testing.T, cfg guestd.Config) *fakeVM {
	t.Helper()
	sock := shortSock(t, "pt")
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	inner := &chanListener{ch: make(chan net.Conn), done: make(chan struct{})}
	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	vm := &fakeVM{uds: sock}
	nop := guestd.System{
		SetClock:   func(time.Time) error { return nil },
		AddEntropy: func([]byte) (bool, error) { return true, nil },
		GrowFS:     func(string, uint64) (uint64, uint64, error) { return 0, 0, nil },
		InstallCA: func(pem []byte) error {
			vm.casMu.Lock()
			defer vm.casMu.Unlock()
			vm.cas = append(vm.cas, pem)
			return nil
		},
	}
	d, err := guestd.NewServer(cfg, nop, m)
	if err != nil {
		t.Fatal(err)
	}
	gs := d.NewGRPCServer()
	go func() { _ = gs.Serve(inner) }()
	t.Cleanup(func() {
		_ = ln.Close()
		_ = os.Remove(sock)
		gs.Stop()
		_ = inner.Close()
		m.Shutdown()
	})
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				br := bufio.NewReader(c)
				line, err := br.ReadString('\n')
				if err != nil || strings.TrimSpace(line) != "CONNECT 52" {
					// Firecracker closes the connection when nothing listens.
					_ = c.Close()
					return
				}
				vm.connects.Add(1)
				_, _ = io.WriteString(c, "OK 1\n")
				select {
				case inner.ch <- &readConn{Conn: c, r: br}:
				case <-inner.done:
					_ = c.Close()
				}
			}(c)
		}
	}()
	return vm
}

// ptAgent is a node agent with a pass-through and one running VM per
// sandbox in uds.
type ptAgent struct {
	m     *agent.Manager
	l     *mapLauncher
	pt    *Passthrough
	saves *Saves
	vms   map[string]agent.VM
	conn  *grpc.ClientConn
}

type mapLauncher struct {
	uds   map[string]string
	mu    sync.Mutex
	procs map[string]*guestProc
	// fail, if set, fails every launch.
	fail error
}

func (l *mapLauncher) Launch(_ context.Context, s agent.LaunchSpec) (agent.Process, error) {
	if l.fail != nil {
		return nil, l.fail
	}
	p := &guestProc{uds: l.uds[s.ID], done: make(chan struct{})}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.procs[s.ID] = p
	return p, nil
}

// exit makes the VM process of id exit without Stop.
func (l *mapLauncher) exit(id string) {
	l.mu.Lock()
	p := l.procs[id]
	l.mu.Unlock()
	p.once.Do(func() { close(p.done) })
}

func newPTAgent(t *testing.T, mtls bool, uds map[string]string, opts ...func(*Service)) *ptAgent {
	t.Helper()
	dir := t.TempDir()
	if _, err := template.WriteFake(filepath.Join(dir, "tpl"), "t1", template.Key{VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, FirecrackerVersion: "v1.17.0"}); err != nil {
		t.Fatal(err)
	}
	uids, _ := jailer.NewUIDPool(1000, 10)
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	l := &mapLauncher{uds: uds, procs: map[string]*guestProc{}}
	m := agent.NewManager(agent.Config{StartTimeout: time.Second, StopTimeout: time.Second, MaxScratchGiB: 10, TombstoneTTL: time.Hour},
		&template.Store{Dir: filepath.Join(dir, "tpl")}, l, bigStats{}, uids,
		agent.Versions{Firecracker: "v1.17.0"}, log)
	pt := NewPassthrough(m, 0, log)
	a := &ptAgent{m: m, l: l, pt: pt, vms: map[string]agent.VM{}}
	for id := range uds {
		vm, _, err := m.Create(context.Background(), agent.CreateRequest{SandboxID: id, Attempt: 1, Template: "t1",
			VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, TenantID: "public"})
		if err != nil {
			t.Fatal(err)
		}
		a.vms[id] = vm
	}
	svc := &Service{M: m, Keys: pt}
	for _, o := range opts {
		o(svc)
	}
	sopts := pt.ServerOptions()
	var ln net.Listener
	var target string
	var clientCreds credentials.TransportCredentials
	if mtls {
		certs, err := testcerts.Write(dir)
		if err != nil {
			t.Fatal(err)
		}
		creds, err := MTLSCredentials(certs.ServerCert, certs.ServerKey, certs.ClientCA)
		if err != nil {
			t.Fatal(err)
		}
		sopts = append(sopts, grpc.Creds(creds))
		if ln, err = net.Listen("tcp", "127.0.0.1:0"); err != nil {
			t.Fatal(err)
		}
		target = ln.Addr().String()
		clientCreds = credentials.NewTLS(clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	} else {
		sock := shortSock(t, "ha")
		var err error
		if ln, err = ListenUnix(sock); err != nil {
			t.Fatal(err)
		}
		target = "unix://" + sock
		clientCreds = insecure.NewCredentials()
	}
	saves, err := NewSaves(&Saves{M: m, PT: pt, Dir: filepath.Join(dir, "captures"), Log: log,
		Transfer: &transfer.Client{AllowHTTP: true, Parallel: 4, PartBytes: 1 << 20}})
	if err != nil {
		t.Fatal(err)
	}
	a.saves = saves
	svc.Saves = saves
	srv := NewServer(svc, sopts...)
	go func() { _ = srv.Serve(ln) }()
	t.Cleanup(srv.Stop)
	conn, err := grpc.NewClient(target, grpc.WithTransportCredentials(clientCreds))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	a.conn = conn
	return a
}

func (a *ptAgent) daemon() sdpb.SandboxdClient { return sdpb.NewSandboxdClient(a.conn) }

func to(ctx context.Context, id string) context.Context {
	return metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, id, guestd.KeyHeader, vmKey)
}

// initVM installs the key as Create does, then runs Init through the
// pass-through.
func initVM(t *testing.T, a *ptAgent, id string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := a.pt.InstallKey(ctx, a.vms[id], vmKey, nil); err != nil {
		t.Fatalf("install key %s: %v", id, err)
	}
	if _, err := a.daemon().Init(to(ctx, id), &sdpb.InitRequest{
		HostTime: timestamppb.Now(), Entropy: make([]byte, 32), SandboxId: id, Generation: a.vms[id].Generation,
	}); err != nil {
		t.Fatalf("init %s: %v", id, err)
	}
}

func errInfo(err error) (domain, reason string) {
	for _, d := range status.Convert(err).Details() {
		if info, ok := d.(*errdetails.ErrorInfo); ok {
			return info.GetDomain(), info.GetReason()
		}
	}
	return "", ""
}

type runOut struct {
	execID string
	stdout string
	result *sdpb.ExecResult
}

func collect(s grpc.ServerStreamingClient[sdpb.ExecEvent]) (runOut, error) {
	var out runOut
	for {
		ev, err := s.Recv()
		if errors.Is(err, io.EOF) {
			return out, nil
		}
		if err != nil {
			return out, err
		}
		switch e := ev.GetEvent().(type) {
		case *sdpb.ExecEvent_Started:
			out.execID = e.Started.GetExecutionId()
		case *sdpb.ExecEvent_Output:
			if e.Output.GetStream() == sdpb.OutputStream_STDOUT {
				out.stdout += string(e.Output.GetData())
			}
		case *sdpb.ExecEvent_Result:
			out.result = e.Result
		}
	}
}

func TestPassthroughOverMTLS(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, true, map[string]string{sandbox: vm.uds})
	c := a.daemon()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Health needs no key; it shows the daemon answered through the agent.
	if _, err := c.Health(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox), &sdpb.HealthRequest{}); err != nil {
		t.Fatalf("health: %v", err)
	}
	// A daemon error passes through unchanged (daemon domain and reason).
	rs, err := c.Run(to(ctx, sandbox), &sdpb.RunRequest{Command: &sdpb.Command{Argv: []string{"true"}}})
	if err == nil {
		_, err = collect(rs)
	}
	if d, r := errInfo(err); status.Code(err) != codes.FailedPrecondition || d != guestd.ErrorDomain || r != "KEY_NOT_SET" {
		t.Fatalf("run before the key: %v (%s %s)", err, d, r)
	}
	initVM(t, a, sandbox)

	// Run streams stdout and the result.
	s, err := c.Run(to(ctx, sandbox), &sdpb.RunRequest{Command: &sdpb.Command{Argv: []string{"sh", "-c", "echo hi; echo err >&2; exit 3"}}})
	if err != nil {
		t.Fatal(err)
	}
	out, err := collect(s)
	if err != nil || out.stdout != "hi\n" || out.result.GetExitCode() != 3 {
		t.Fatalf("run: %+v %v", out, err)
	}

	// Start + Interact (stdin) + Stream.
	st, err := c.Start(to(ctx, sandbox), &sdpb.StartRequest{Command: &sdpb.Command{Argv: []string{"cat"}, Stdin: true}})
	if err != nil {
		t.Fatal(err)
	}
	id := st.GetStarted().GetExecutionId()
	if _, err := c.Interact(to(ctx, sandbox), &sdpb.InteractRequest{ExecutionId: id, Data: []byte("ping\n"), CloseStdin: true}); err != nil {
		t.Fatal(err)
	}
	ss, err := c.Stream(to(ctx, sandbox), &sdpb.StreamRequest{ExecutionId: id})
	if err != nil {
		t.Fatal(err)
	}
	out, err = collect(ss)
	if err != nil || out.stdout != "ping\n" || out.result.GetCompletion() != sdpb.Completion_EXITED {
		t.Fatalf("stream: %+v %v", out, err)
	}

	// The daemon key goes through: a wrong one is the daemon's UNAUTHENTICATED.
	bad := metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox, guestd.KeyHeader, strings.Repeat("x", 32))
	if _, err := c.Inspect(bad, &sdpb.InspectRequest{ExecutionId: id}); status.Code(err) != codes.Unauthenticated {
		t.Fatalf("wrong key: %v", err)
	}

	// The typed HostAgent service still works on the same server.
	l, err := pb.NewHostAgentClient(a.conn).List(ctx, &pb.ListRequest{})
	if err != nil || len(l.GetVms()) != 1 {
		t.Fatalf("list: %v %v", l, err)
	}
	if n := vm.connects.Load(); n != 1 {
		t.Fatalf("%d vsock connections, want 1 reused", n)
	}
}

func TestPassthroughTypedErrors(t *testing.T) {
	vm := startFakeVM(t)
	// sandbox2's VM has nothing on port 52: its socket refuses CONNECT.
	refuse := shortSock(t, "pr")
	rln, err := net.Listen("unix", refuse)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = rln.Close(); _ = os.Remove(refuse) })
	go func() {
		for {
			c, err := rln.Accept()
			if err != nil {
				return
			}
			_ = c.Close()
		}
	}()
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds, sandbox2: refuse})
	c := a.daemon()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	health := func(ctx context.Context) error {
		_, err := c.Health(ctx, &sdpb.HealthRequest{})
		return err
	}
	check := func(name string, err error, code codes.Code, reason pb.ErrorReason) {
		t.Helper()
		if status.Code(err) != code || apierr.FromStatus(err) != reason {
			t.Errorf("%s: code %s reason %s (%v)", name, status.Code(err), apierr.FromStatus(err), err)
		}
	}
	check("no sandbox id", health(ctx), codes.InvalidArgument, pb.ErrorReason_INVALID_ARGUMENT)
	check("bad sandbox id", health(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, "nope")),
		codes.InvalidArgument, pb.ErrorReason_INVALID_ARGUMENT)
	check("unknown sandbox", health(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, "33333333-3333-4333-8333-333333333333")),
		codes.NotFound, pb.ErrorReason_SANDBOX_NOT_FOUND)
	check("daemon not listening", health(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox2)),
		codes.Unavailable, pb.ErrorReason_GUEST_UNREACHABLE)

	// Other services get UNIMPLEMENTED, also with a sandbox ID.
	err = a.conn.Invoke(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox),
		"/grpc.health.v1.Health/Check", &emptypb.Empty{}, &emptypb.Empty{})
	if status.Code(err) != codes.Unimplemented {
		t.Errorf("other service: %v", err)
	}

	// A VM that exited (no Stop yet) is VM_NOT_RUNNING; after Stop it is gone.
	a.l.exit(sandbox2)
	for a.m.List()[1].State != pb.VMState_VM_STATE_EXITED {
		if ctx.Err() != nil {
			t.Fatal("VM did not show as exited")
		}
		time.Sleep(time.Millisecond)
	}
	check("exited VM", health(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox2)),
		codes.FailedPrecondition, pb.ErrorReason_VM_NOT_RUNNING)
	vm2 := a.vms[sandbox2]
	if _, err := a.m.Stop(ctx, sandbox2, vm2.Attempt, vm2.Generation); err != nil {
		t.Fatal(err)
	}
	check("stopped sandbox", health(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox2)),
		codes.NotFound, pb.ErrorReason_SANDBOX_NOT_FOUND)
	if err := health(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox)); err != nil {
		t.Errorf("health of the good VM: %v", err)
	}
}

// TestPassthroughReusesOneConnection runs many calls at once (-race): one
// vsock connection per VM instance.
func TestPassthroughReusesOneConnection(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds})
	initVM(t, a, sandbox)
	c := a.daemon()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	var wg sync.WaitGroup
	errs := make(chan error, 40)
	for i := 0; i < 40; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s, err := c.Run(to(ctx, sandbox), &sdpb.RunRequest{Command: &sdpb.Command{Argv: []string{"echo", "x"}}})
			if err != nil {
				errs <- err
				return
			}
			out, err := collect(s)
			if err == nil && out.stdout != "x\n" {
				err = errors.New("stdout " + out.stdout)
			}
			if err != nil {
				errs <- err
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Error(err)
	}
	if n := vm.connects.Load(); n != 1 {
		t.Fatalf("%d vsock connections, want 1", n)
	}
	if gen, ok := a.pt.Cached(sandbox); !ok || gen != a.vms[sandbox].Generation {
		t.Fatalf("cached generation %d %v, want %d", gen, ok, a.vms[sandbox].Generation)
	}
}

// TestPassthroughStopDuringCall stops the VM while a Run streams (-race).
// The call ends at once with VM_NOT_RUNNING and the connection is dropped.
func TestPassthroughStopDuringCall(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds})
	initVM(t, a, sandbox)
	c := a.daemon()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	s, err := c.Run(to(ctx, sandbox), &sdpb.RunRequest{Command: &sdpb.Command{Argv: []string{"sleep", "30"}}})
	if err != nil {
		t.Fatal(err)
	}
	if ev, err := s.Recv(); err != nil || ev.GetStarted() == nil {
		t.Fatalf("first event: %v %v", ev, err)
	}
	done := make(chan error, 1)
	go func() {
		_, err := collect(s)
		done <- err
	}()
	v := a.vms[sandbox]
	t0 := time.Now()
	if _, err := a.m.Stop(ctx, sandbox, v.Attempt, v.Generation); err != nil {
		t.Fatal(err)
	}
	err = <-done
	if status.Code(err) != codes.FailedPrecondition || apierr.FromStatus(err) != pb.ErrorReason_VM_NOT_RUNNING {
		t.Fatalf("call during stop: %v", err)
	}
	if d := time.Since(t0); d > 5*time.Second {
		t.Fatalf("call ended %s after Stop", d)
	}
	if _, ok := a.pt.Cached(sandbox); ok {
		t.Fatal("connection still cached after Stop")
	}
}

// TestPassthroughClientCancel cancels a streaming call; the agent ends the
// daemon call and serves the next one.
func TestPassthroughClientCancel(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds})
	initVM(t, a, sandbox)
	c := a.daemon()
	ctx, cancel := context.WithCancel(context.Background())
	s, err := c.Run(to(ctx, sandbox), &sdpb.RunRequest{Command: &sdpb.Command{Argv: []string{"sleep", "30"}}})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Recv(); err != nil {
		t.Fatal(err)
	}
	cancel()
	if _, err := collect(s); status.Code(err) != codes.Canceled {
		t.Fatalf("cancelled call: %v", err)
	}
	ctx2, cancel2 := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel2()
	if _, err := c.Health(to(ctx2, sandbox), &sdpb.HealthRequest{}); err != nil {
		t.Fatalf("next call: %v", err)
	}
}

// A call that read an older generation must not replace or close the cached
// connection of a newer VM instance.
func TestPassthroughStaleCallKeepsNewerConnection(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds})
	gen := a.vms[sandbox].Generation
	newer := &upstream{gen: gen + 1, dropped: make(chan struct{})}
	conn, err := grpc.NewClient("passthrough:///unused", grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	newer.conn = conn
	t.Cleanup(newer.close)
	a.pt.mu.Lock()
	a.pt.conns[sandbox] = newer
	a.pt.mu.Unlock()

	if _, err := a.pt.get(sandbox); err == nil {
		t.Fatal("stale call got a connection")
	}
	if newer.isDropped() {
		t.Fatal("stale call closed the newer connection")
	}
	if g, ok := a.pt.Cached(sandbox); !ok || g != gen+1 {
		t.Fatalf("cached generation %d %v, want %d", g, ok, gen+1)
	}
}

// Create installs sandboxd_key in the daemon before it returns; callers
// cannot install a key through the pass-through.
func TestCreateInstallsKey(t *testing.T) {
	vm := startFakeVM(t)
	// sandbox2's VM has no daemon: its socket refuses CONNECT.
	refuse := shortSock(t, "pk")
	rln, err := net.Listen("unix", refuse)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = rln.Close(); _ = os.Remove(refuse) })
	go func() {
		for {
			c, err := rln.Accept()
			if err != nil {
				return
			}
			_ = c.Close()
		}
	}()
	a := newPTAgent(t, true, map[string]string{sandbox: vm.uds, sandbox2: refuse})
	a.pt.KeyTimeout = 500 * time.Millisecond
	ha := pb.NewHostAgentClient(a.conn)
	c := a.daemon()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	create := func(id, key string) (*pb.CreateResponse, error) {
		return ha.Create(ctx, &pb.CreateRequest{SandboxId: id, Attempt: 1, Template: "t1", Vcpus: 2, MemMib: 4096,
			ScratchGib: 1, TenantId: "public", SandboxdKey: key})
	}
	initReq := &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: make([]byte, 32), SandboxId: sandbox}

	// No key yet: the daemon refuses Init, and callers cannot set a key.
	if _, err := c.Init(to(ctx, sandbox), initReq); status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("init before the key: %v", err)
	}
	_, err = c.SetKey(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox), &sdpb.SetKeyRequest{Key: strings.Repeat("a", 32)})
	if status.Code(err) != codes.PermissionDenied || apierr.FromStatus(err) != pb.ErrorReason_METHOD_NOT_ALLOWED {
		t.Fatalf("SetKey through the pass-through: %v", err)
	}

	if _, err := create(sandbox, "short"); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("bad key: %v", err)
	}
	r, err := create(sandbox, vmKey)
	if err != nil || r.GetCreated() {
		t.Fatalf("create with key: %v %v", r, err)
	}
	// A repeat Create with the same key succeeds; another key is refused.
	if _, err := create(sandbox, vmKey); err != nil {
		t.Fatalf("repeat create: %v", err)
	}
	_, err = create(sandbox, strings.Repeat("z", 32))
	if status.Code(err) != codes.FailedPrecondition || apierr.FromStatus(err) != pb.ErrorReason_GUEST_KEY_REJECTED {
		t.Fatalf("create with another key: %v", err)
	}
	if _, err := c.Init(to(ctx, sandbox), initReq); err != nil {
		t.Fatalf("init with the installed key: %v", err)
	}

	_, err = create(sandbox2, vmKey)
	if status.Code(err) != codes.Unavailable || apierr.FromStatus(err) != pb.ErrorReason_GUEST_UNREACHABLE {
		t.Fatalf("create without a daemon: %v", err)
	}
}

// Create sends the deployment egress CA with the key; Init installs it. A CA
// source with no CA fails Create before any VM starts.
func TestCreateSendsEgressCA(t *testing.T) {
	vm := startFakeVM(t)
	ca, err := testcerts.NewCA("deployment egress CA")
	if err != nil {
		t.Fatal(err)
	}
	caFile := filepath.Join(t.TempDir(), "ca.crt")
	src := &egressca.Cached{Src: egressca.File{Path: caFile}, TTL: time.Minute, RetryAfter: time.Nanosecond}
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds}, func(s *Service) { s.EgressCA = src })
	ha := pb.NewHostAgentClient(a.conn)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	launches := a.m.List()
	_, err = ha.Create(ctx, &pb.CreateRequest{SandboxId: sandbox2, Attempt: 1, Template: "t1", Vcpus: 2, MemMib: 4096,
		ScratchGib: 1, TenantId: "public", SandboxdKey: vmKey})
	if status.Code(err) != codes.Unavailable || apierr.FromStatus(err) != pb.ErrorReason_EGRESS_CA_UNAVAILABLE {
		t.Fatalf("create with no CA file: %v", err)
	}
	if len(a.m.List()) != len(launches) {
		t.Fatal("a VM started without a CA")
	}
	if err := os.WriteFile(caFile, ca.PEM, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: sandbox, Attempt: 1, Template: "t1", Vcpus: 2, MemMib: 4096,
		ScratchGib: 1, TenantId: "public", SandboxdKey: vmKey}); err != nil {
		t.Fatal(err)
	}
	r, err := a.daemon().Init(to(ctx, sandbox), &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: make([]byte, 32), SandboxId: sandbox})
	if err != nil || !r.GetEgressCaInstalled() {
		t.Fatalf("init: %v %v", r, err)
	}
	vm.casMu.Lock()
	defer vm.casMu.Unlock()
	if len(vm.cas) != 1 || string(vm.cas[0]) != string(ca.PEM) {
		t.Fatalf("installed %d CAs", len(vm.cas))
	}
}

// A caller that gives up during the key install is not a guest key fault:
// the Create shows as canceled, not as GUEST_KEY_REJECTED.
func TestInstallKeyCallerGivesUp(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds})
	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	expired, cancel2 := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel2()
	for name, tc := range map[string]struct {
		ctx  context.Context
		want error
	}{
		"canceled": {canceled, context.Canceled},
		"deadline": {expired, context.DeadlineExceeded},
	} {
		err := a.pt.InstallKey(tc.ctx, a.vms[sandbox], vmKey, nil)
		if !errors.Is(err, tc.want) || reasonOf(err) != "" {
			t.Errorf("%s: %v (reason %q), want %v", name, err, reasonOf(err), tc.want)
		}
		if got := createResult(nil, toStatus(err), true); got != metrics.CreateCanceled {
			t.Errorf("%s: create result %s, want canceled", name, got)
		}
	}
}
