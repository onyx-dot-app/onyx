package guestd

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// Commands start in the session directory, but may use any path.
func TestCommandSessionDirAndUnscopedPaths(t *testing.T) {
	c, sessions := fileHarness(t)
	ctx := keyed(context.Background())
	elsewhere, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	s, err := c.Run(ctx, &pb.RunRequest{Command: &pb.Command{
		Argv: []string{"sh", "-c", `pwd; echo x > "$1/out.txt"; cd ..; pwd`, "sh", elsewhere}, SessionId: fileSession,
	}})
	if err != nil {
		t.Fatal(err)
	}
	r := collect(t, s)
	dir := filepath.Join(sessions, fileSession)
	if r.result.GetExitCode() != 0 || r.stdout != dir+"\n"+sessions+"\n" {
		t.Fatalf("session cwd: %q %q %v", r.stdout, r.stderr, r.result)
	}
	if b, err := os.ReadFile(filepath.Join(elsewhere, "out.txt")); err != nil || string(b) != "x\n" {
		t.Fatalf("write outside the session: %q %v", b, err)
	}

	// A relative cwd is below the session; an absolute one is used as is.
	if err := os.MkdirAll(filepath.Join(dir, "sub"), 0o755); err != nil {
		t.Fatal(err)
	}
	for cwd, want := range map[string]string{"sub": filepath.Join(dir, "sub"), elsewhere: elsewhere} {
		s, err := c.Run(ctx, &pb.RunRequest{Command: &pb.Command{Argv: []string{"pwd"}, Cwd: cwd, SessionId: fileSession}})
		if err != nil {
			t.Fatal(err)
		}
		if r := collect(t, s); strings.TrimSpace(r.stdout) != want {
			t.Errorf("cwd %q: %q", cwd, r.stdout)
		}
	}
	// No session: the default stays "/".
	s, _ = c.Run(ctx, &pb.RunRequest{Command: &pb.Command{Argv: []string{"pwd"}}})
	if r := collect(t, s); r.stdout != "/\n" {
		t.Errorf("no session: %q", r.stdout)
	}
	for _, cwd := range []string{"", "/tmp"} {
		if _, err := c.Start(ctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"pwd"}, Cwd: cwd, SessionId: "../x"}}); reason(err) != "INVALID_ARGUMENT" {
			t.Errorf("bad session id, cwd %q: %v", cwd, err)
		}
	}
	// A session with an absolute cwd still gets its directory.
	if _, err := c.Start(ctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"pwd"}, Cwd: elsewhere, SessionId: "s-abs"}}); err != nil {
		t.Fatal(err)
	}
	if fi, err := os.Stat(filepath.Join(sessions, "s-abs")); err != nil || !fi.IsDir() {
		t.Errorf("session dir with an absolute cwd: %v", err)
	}
}

func TestCommandEnvDefaults(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{BaseEnv: map[string]string{"PATH": os.Getenv("PATH"), "TERM": "linux", "NO_COLOR": "base"}})
	c, _ := h.client()
	if _, err := c.SetKey(context.Background(), &pb.SetKeyRequest{Key: testKey}); err != nil {
		t.Fatal(err)
	}
	init := initReq()
	init.Env = map[string]string{"GIT_PAGER": "less"}
	if _, err := c.Init(keyed(context.Background()), init); err != nil {
		t.Fatal(err)
	}
	s, err := c.Run(keyed(context.Background()), &pb.RunRequest{Command: &pb.Command{
		Argv: []string{"sh", "-c", `echo "$NO_COLOR $TERM $PAGER $GIT_PAGER $GH_PAGER $LANG $LC_ALL"`},
		Env:  map[string]string{"PAGER": "more"},
	}})
	if err != nil {
		t.Fatal(err)
	}
	// The defaults beat the daemon's env (TERM=linux); Init and the command env beat the defaults.
	if r := collect(t, s); r.stdout != "1 dumb more less cat C.UTF-8 C.UTF-8\n" {
		t.Fatalf("env %q", r.stdout)
	}
}

func TestCancelWithSignal(t *testing.T) {
	h := newHarness(t, execs.Config{}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())

	// The command handles SIGINT (Ctrl-C) and exits on its own.
	st, err := c.Start(ctx, &pb.StartRequest{Command: sh(`trap 'echo got-int; exit 7' INT; echo ready; while :; do sleep 0.05; done`)})
	if err != nil {
		t.Fatal(err)
	}
	id := st.GetStarted().GetExecutionId()
	waitOutput(t, c, id, "ready")
	cr, err := c.Cancel(ctx, &pb.CancelRequest{ExecutionId: id, Signal: pb.CancelSignal_CANCEL_SIGNAL_SIGINT})
	if err != nil || !cr.GetSignaled() || cr.GetResult() != nil {
		t.Fatalf("SIGINT cancel: %v %v", cr, err)
	}
	ss, _ := c.Stream(ctx, &pb.StreamRequest{ExecutionId: id})
	if r := collect(t, ss); r.result.GetCompletion() != pb.Completion_EXITED || r.result.GetExitCode() != 7 || !strings.Contains(r.stdout, "got-int") {
		t.Fatalf("handled SIGINT: %q %v", r.stdout, r.result)
	}

	// A child in the process group gets it too; a command that dies of it is CANCELED.
	st, _ = c.Start(ctx, &pb.StartRequest{Command: sh(`echo ready; sleep 30; echo after`)})
	id = st.GetStarted().GetExecutionId()
	waitOutput(t, c, id, "ready")
	if cr, err := c.Cancel(ctx, &pb.CancelRequest{ExecutionId: id, Signal: pb.CancelSignal_CANCEL_SIGNAL_SIGTERM}); err != nil || !cr.GetSignaled() {
		t.Fatalf("SIGTERM cancel: %v %v", cr, err)
	}
	ss, _ = c.Stream(ctx, &pb.StreamRequest{ExecutionId: id})
	r := collect(t, ss)
	if r.result.GetCompletion() != pb.Completion_CANCELED || r.result.GetSignal() != int32(syscall.SIGTERM) || strings.Contains(r.stdout, "after") {
		t.Fatalf("SIGTERM result %q %v", r.stdout, r.result)
	}
	// A signal to an ended execution returns its result.
	cr, err = c.Cancel(ctx, &pb.CancelRequest{ExecutionId: id, Signal: pb.CancelSignal_CANCEL_SIGNAL_SIGINT})
	if err != nil || !cr.GetAlreadyEnded() || cr.GetSignaled() || cr.GetResult().GetCompletion() != pb.Completion_CANCELED {
		t.Fatalf("ended: %v %v", cr, err)
	}

	// SIGKILL is the default kill: the cgroup (here the group) dies and Cancel waits.
	st, _ = c.Start(ctx, &pb.StartRequest{Command: sh(`trap '' INT TERM; sleep 30`)})
	cr, err = c.Cancel(ctx, &pb.CancelRequest{ExecutionId: st.GetStarted().GetExecutionId(), Signal: pb.CancelSignal_CANCEL_SIGNAL_SIGKILL})
	if err != nil || cr.GetResult().GetCompletion() != pb.Completion_CANCELED || cr.GetSignaled() {
		t.Fatalf("SIGKILL: %v %v", cr, err)
	}
	if _, err := c.Cancel(ctx, &pb.CancelRequest{ExecutionId: id, Signal: 99}); reason(err) != "INVALID_ARGUMENT" {
		t.Fatalf("unknown signal: %v", err)
	}
}

func TestExecutionCapReason(t *testing.T) {
	h := newHarness(t, execs.Config{MaxTracked: 2}, Config{})
	c := h.initialized()
	ctx := keyed(context.Background())
	var ids []string
	for range 2 {
		st, err := c.Start(ctx, &pb.StartRequest{Command: sh("sleep 30")})
		if err != nil {
			t.Fatal(err)
		}
		ids = append(ids, st.GetStarted().GetExecutionId())
	}
	if _, err := c.Start(ctx, &pb.StartRequest{Command: sh("true")}); reason(err) != "EXECUTION_CAP_REACHED" {
		t.Fatalf("cap: %v", err)
	}
	if _, err := c.Cancel(ctx, &pb.CancelRequest{ExecutionId: ids[0]}); err != nil {
		t.Fatal(err)
	}
	// The ended record makes room.
	if _, err := c.Start(ctx, &pb.StartRequest{Command: sh("true")}); err != nil {
		t.Fatalf("after cancel: %v", err)
	}
	if _, err := c.Inspect(ctx, &pb.InspectRequest{ExecutionId: ids[0]}); reason(err) != "EXECUTION_NOT_FOUND" {
		t.Fatalf("evicted record: %v", err)
	}
}

// waitOutput streams until stdout has want.
func waitOutput(t *testing.T, c pb.SandboxdClient, id, want string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(keyed(context.Background()), 10*time.Second)
	defer cancel()
	s, err := c.Stream(ctx, &pb.StreamRequest{ExecutionId: id})
	if err != nil {
		t.Fatal(err)
	}
	var out strings.Builder
	for !strings.Contains(out.String(), want) {
		ev, err := s.Recv()
		if err != nil {
			t.Fatalf("waiting for %q: %v (got %q)", want, err, out.String())
		}
		out.Write(ev.GetOutput().GetData())
	}
}

// With no session, the file calls take absolute VM paths, but not the
// daemon's own state.
func TestFileCallsWithoutSession(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(root, "state")
	fs, err := files.New(files.Config{SessionsRoot: filepath.Join(root, "sessions"), DeniedVMPaths: []string{state}})
	if err != nil {
		t.Fatal(err)
	}
	h := newHarness(t, execs.Config{}, Config{Files: fs})
	c := h.initialized()
	ctx := keyed(context.Background())
	target := filepath.Join(root, "tmp", "a", "b.txt")

	ws, _ := c.WriteFile(ctx)
	_ = ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Header{Header: &pb.WriteFileHeader{Path: target, Size: 2, MakeParents: true}}})
	_ = ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Data{Data: []byte("hi")}})
	wr, err := ws.CloseAndRecv()
	if err != nil || wr.GetInfo().GetPath() != target {
		t.Fatalf("write: %v %v", wr, err)
	}
	rs, _ := c.ReadFile(ctx, &pb.ReadFileRequest{Path: target})
	first, err := rs.Recv()
	if err != nil || first.GetInfo().GetPath() != target {
		t.Fatalf("read info: %v %v", first, err)
	}
	if d, err := rs.Recv(); err != nil || string(d.GetData()) != "hi" {
		t.Fatalf("read data: %v %v", d, err)
	}
	lr, err := c.ListFiles(ctx, &pb.ListFilesRequest{Path: filepath.Join(root, "tmp"), Recursive: true})
	if err != nil || len(lr.GetEntries()) != 2 || lr.GetEntries()[1].GetPath() != target {
		t.Fatalf("list: %v %v", lr, err)
	}
	if dr, err := c.DeleteFile(ctx, &pb.DeleteFileRequest{Path: target}); err != nil || !dr.GetDeleted() {
		t.Fatalf("delete: %v %v", dr, err)
	}

	// Denied: the state dir, a link into it, a relative path, the VM root.
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(state, "key"), []byte("k"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "link")
	if err := os.Symlink(filepath.Join(state, "key"), link); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{filepath.Join(state, "key"), link, "relative/path", state + "/../state/key"} {
		rs, _ := c.ReadFile(ctx, &pb.ReadFileRequest{Path: p})
		if _, err := rs.Recv(); reason(err) != "INVALID_ARGUMENT" {
			t.Errorf("read %s: %v", p, err)
		}
	}
	if _, err := c.DeleteFile(ctx, &pb.DeleteFileRequest{Path: "/", Recursive: true}); reason(err) != "INVALID_ARGUMENT" {
		t.Errorf("delete /: %v", err)
	}
	ws, _ = c.WriteFile(ctx)
	_ = ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Header{Header: &pb.WriteFileHeader{Path: filepath.Join(state, "new"), Size: 0}}})
	if _, err := ws.CloseAndRecv(); reason(err) != "INVALID_ARGUMENT" {
		t.Errorf("write into the state dir: %v", err)
	}
	// make_parents through a link into the state dir makes nothing there.
	if err := os.Symlink(state, filepath.Join(root, "statelink")); err != nil {
		t.Fatal(err)
	}
	ws, _ = c.WriteFile(ctx)
	_ = ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Header{Header: &pb.WriteFileHeader{
		Path: filepath.Join(root, "statelink", "made", "f"), Size: 0, MakeParents: true}}})
	if _, err := ws.CloseAndRecv(); reason(err) != "INVALID_ARGUMENT" {
		t.Errorf("make_parents into the state dir: %v", err)
	}
	if _, err := os.Stat(filepath.Join(state, "made")); !os.IsNotExist(err) {
		t.Errorf("a directory was made in the state dir: %v", err)
	}
	// Recursive calls on a parent of the state dir do not reach it.
	lr, err = c.ListFiles(ctx, &pb.ListFilesRequest{Path: root, Recursive: true})
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range lr.GetEntries() {
		if e.GetPath() == state || strings.HasPrefix(e.GetPath(), state+"/") {
			t.Errorf("list of %s shows %s", root, e.GetPath())
		}
	}
	zs, _ := c.ZipFiles(ctx, &pb.ZipFilesRequest{Path: root})
	var zipped []byte
	for {
		m, err := zs.Recv()
		if err != nil {
			break
		}
		zipped = append(zipped, m.GetData()...)
	}
	if len(zipped) == 0 || bytes.Contains(zipped, []byte("state/key")) {
		t.Errorf("zip of %s: %d bytes, has state/key: %v", root, len(zipped), bytes.Contains(zipped, []byte("state/key")))
	}
	if _, err := c.DeleteFile(ctx, &pb.DeleteFileRequest{Path: root, Recursive: true}); reason(err) != "INVALID_ARGUMENT" {
		t.Errorf("recursive delete of a parent of the state dir: %v", err)
	}
	if _, err := os.Stat(filepath.Join(state, "key")); err != nil {
		t.Errorf("state key removed: %v", err)
	}

	// A write through a link in the last part replaces the link's target.
	report, current := filepath.Join(root, "report.txt"), filepath.Join(root, "current")
	if err := os.WriteFile(report, []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(report, current); err != nil {
		t.Fatal(err)
	}
	ws, _ = c.WriteFile(ctx)
	_ = ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Header{Header: &pb.WriteFileHeader{Path: current, Size: 3, Overwrite: true}}})
	_ = ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Data{Data: []byte("new")}})
	if wr, err := ws.CloseAndRecv(); err != nil || wr.GetInfo().GetPath() != current {
		t.Fatalf("write through link: %v %v", wr, err)
	}
	if b, _ := os.ReadFile(report); string(b) != "new" {
		t.Errorf("link target has %q", b)
	}
	if fi, err := os.Lstat(current); err != nil || fi.Mode()&os.ModeSymlink == 0 {
		t.Errorf("the link was replaced: %v %v", fi, err)
	}
	// A delete removes the link, not its target.
	if dr, err := c.DeleteFile(ctx, &pb.DeleteFileRequest{Path: current}); err != nil || !dr.GetDeleted() {
		t.Fatalf("delete link: %v %v", dr, err)
	}
	if _, err := os.Stat(report); err != nil {
		t.Errorf("link target removed: %v", err)
	}

	// Uploads and saves still need a session.
	us, _ := c.UploadFile(ctx)
	_ = us.Send(&pb.UploadFileRequest{Part: &pb.UploadFileRequest_Header{Header: &pb.UploadFileHeader{FileName: "a.txt", Size: 0}}})
	if _, err := us.CloseAndRecv(); reason(err) != "INVALID_ARGUMENT" {
		t.Errorf("upload without a session: %v", err)
	}
}
