//go:build kvm && linux

package kvmtest

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const (
	daemonPort = 52
	vmMemMiB   = 2048
	scratchGiB = 2 // the image is 1 GiB: Init grows it
)

type env struct {
	FCBin, ImgDir, WorkDir string
	VMs                    int
	RestoreGap             time.Duration
	BootArgs               string // KVM_BOOT_ARGS
	TemplateArgs           string // KVM_TEMPLATE_ARGS: added for the snapshot boot
}

func loadEnv(t *testing.T) env {
	t.Helper()
	get := func(k, def string) string {
		if v := os.Getenv(k); v != "" {
			return v
		}
		return def
	}
	n, err := strconv.Atoi(get("KVM_VMS", "20"))
	if err != nil || n < 1 {
		t.Fatalf("KVM_VMS must be a positive integer, got %q", os.Getenv("KVM_VMS"))
	}
	gap, err := time.ParseDuration(get("KVM_RESTORE_GAP", "20s"))
	if err != nil || gap < 0 {
		t.Fatalf("KVM_RESTORE_GAP must be a duration, got %q", os.Getenv("KVM_RESTORE_GAP"))
	}
	return env{
		FCBin: get("KVM_FC_BIN", "/opt/craft-fc/firecracker"), ImgDir: get("KVM_IMG_DIR", "/opt/craft-fc-test/img"),
		WorkDir: get("KVM_WORK_DIR", "/var/lib/guestd-kvm"), VMs: n, RestoreGap: gap,
		// The Craft root drive (deployment/craft-fc/rootfs).
		BootArgs:     get("KVM_BOOT_ARGS", "console=ttyS0 reboot=k panic=1 pci=off init=/sbin/craft-init"),
		TemplateArgs: get("KVM_TEMPLATE_ARGS", "craft.scratch=defer"),
	}
}

// vm is one Firecracker process. Paths in its config are relative to dir,
// so a snapshot taken in one dir restores in another.
type vm struct {
	dir  string
	cmd  *exec.Cmd
	done chan struct{}
}

func (v *vm) vsock() string { return filepath.Join(v.dir, "v.sock") }

func (v *vm) kill() {
	if v.cmd.Process != nil {
		_ = v.cmd.Process.Kill()
		<-v.done
	}
}

func (v *vm) console() string {
	raw, _ := os.ReadFile(filepath.Join(v.dir, "console.log"))
	if len(raw) > 3000 {
		raw = raw[len(raw)-3000:]
	}
	return string(raw)
}

// prepareDir links the kernel, the root disk and the managed disk (if the
// image dir has managed-empty.ext4), and makes a scratch disk of scratchGiB
// from the empty 1 GiB image.
func prepareDir(t *testing.T, e env, name string) string {
	t.Helper()
	dir := filepath.Join(e.WorkDir, name)
	_ = os.RemoveAll(dir)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{"vmlinux", "rootfs.ext4", "managed-empty.ext4"} {
		src := filepath.Join(e.ImgDir, f)
		if _, err := os.Stat(src); f == "managed-empty.ext4" && err != nil {
			continue
		}
		if err := os.Link(src, filepath.Join(dir, f)); err != nil {
			t.Fatal(err)
		}
	}
	scratch := filepath.Join(dir, "scratch.ext4")
	if out, err := exec.Command("cp", "--sparse=always", filepath.Join(e.ImgDir, "scratch-empty.ext4"), scratch).CombinedOutput(); err != nil {
		t.Fatalf("cp scratch: %v %s", err, out)
	}
	if err := os.Truncate(scratch, scratchGiB<<30); err != nil {
		t.Fatal(err)
	}
	return dir
}

func startFC(t *testing.T, e env, dir string, args ...string) *vm {
	t.Helper()
	logf, err := os.Create(filepath.Join(dir, "console.log"))
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(e.FCBin, append([]string{"--api-sock", "api.sock", "--level", "Warning"}, args...)...)
	cmd.Dir, cmd.Stdout, cmd.Stderr = dir, logf, logf
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	v := &vm{dir: dir, cmd: cmd, done: make(chan struct{})}
	go func() { _ = cmd.Wait(); _ = logf.Close(); close(v.done) }()
	t.Cleanup(v.kill)
	return v
}

// bootVM cold boots a VM from a config file. Drive order: rootfs (vda),
// scratch (vdb), managed (vdc, read-only).
func bootVM(t *testing.T, e env, name, extraArgs string) *vm {
	t.Helper()
	dir := prepareDir(t, e, name)
	drives := []map[string]any{
		{"drive_id": "rootfs", "path_on_host": "rootfs.ext4", "is_root_device": true, "is_read_only": true},
		{"drive_id": "scratch", "path_on_host": "scratch.ext4", "is_root_device": false, "is_read_only": false},
	}
	if _, err := os.Stat(filepath.Join(dir, "managed-empty.ext4")); err == nil {
		drives = append(drives, map[string]any{"drive_id": "managed", "path_on_host": "managed-empty.ext4", "is_root_device": false, "is_read_only": true})
	}
	cfg := map[string]any{
		"boot-source":    map[string]any{"kernel_image_path": "vmlinux", "boot_args": strings.TrimSpace(e.BootArgs + " " + extraArgs)},
		"drives":         drives,
		"machine-config": map[string]any{"vcpu_count": 2, "mem_size_mib": vmMemMiB},
		"vsock":          map[string]any{"guest_cid": 3, "uds_path": "v.sock"},
	}
	raw, _ := json.Marshal(cfg)
	if err := os.WriteFile(filepath.Join(dir, "config.json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return startFC(t, e, dir, "--config-file", "config.json")
}

// fcAPI calls the Firecracker API of a VM.
func fcAPI(ctx context.Context, dir, method, path string, body any) error {
	// Firecracker allows few API connections: no keep-alive.
	hc := &http.Client{Transport: &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		var d net.Dialer
		return d.DialContext(ctx, "unix", filepath.Join(dir, "api.sock"))
	}}}
	var rd io.Reader
	if body != nil {
		raw, _ := json.Marshal(body)
		rd = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, "http://fc"+path, rd)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := hc.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode/100 != 2 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("%s %s: %d %s", method, path, resp.StatusCode, b)
	}
	return nil
}

// waitAPI waits for the Firecracker API socket.
func waitAPI(ctx context.Context, dir string) error {
	for {
		if err := fcAPI(ctx, dir, http.MethodGet, "/", nil); err == nil {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(5 * time.Millisecond):
		}
	}
}

// dialVsock opens a host-initiated vsock stream ("CONNECT <port>").
func dialVsock(ctx context.Context, uds string, port uint32) (net.Conn, error) {
	var d net.Dialer
	c, err := d.DialContext(ctx, "unix", uds)
	if err != nil {
		return nil, err
	}
	if dl, ok := ctx.Deadline(); ok {
		_ = c.SetDeadline(dl)
	}
	if _, err := fmt.Fprintf(c, "CONNECT %d\n", port); err != nil {
		_ = c.Close()
		return nil, err
	}
	// Read the ack one byte at a time so no gRPC bytes are buffered away.
	var line []byte
	b := make([]byte, 1)
	for {
		if _, err := c.Read(b); err != nil {
			_ = c.Close()
			return nil, fmt.Errorf("vsock CONNECT %d: %w", port, err)
		}
		if b[0] == '\n' {
			break
		}
		line = append(line, b[0])
	}
	if !strings.HasPrefix(string(line), "OK ") {
		_ = c.Close()
		return nil, fmt.Errorf("vsock CONNECT %d: %q", port, line)
	}
	_ = c.SetDeadline(time.Time{})
	return c, nil
}

func newConn(v *vm) (*grpc.ClientConn, error) {
	return grpc.NewClient("passthrough:///guestd",
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
			return dialVsock(ctx, v.vsock(), daemonPort)
		}),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
}

// client opens a gRPC connection to the guest daemon of v.
func client(t *testing.T, v *vm) (pb.SandboxdClient, *grpc.ClientConn) {
	t.Helper()
	conn, err := newConn(v)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return pb.NewSandboxdClient(conn), conn
}

// waitHealth calls Health on fresh connections until it answers.
func waitHealth(ctx context.Context, v *vm) (*pb.HealthResponse, error) {
	for {
		conn, err := newConn(v)
		if err != nil {
			return nil, err
		}
		c := pb.NewSandboxdClient(conn)
		hctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
		h, err := c.Health(hctx, &pb.HealthRequest{}, grpc.WaitForReady(false))
		cancel()
		_ = conn.Close()
		if err == nil {
			return h, nil
		}
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("guest daemon did not answer: %v", err)
		case <-time.After(10 * time.Millisecond):
		}
	}
}

func randHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func initRequest(sandboxID string) *pb.InitRequest {
	ent := make([]byte, 64)
	_, _ = rand.Read(ent)
	return &pb.InitRequest{
		HostTime: timestamppb.Now(), Entropy: ent,
		Env: map[string]string{"ONYX_SANDBOX_ID": sandboxID}, SessionIds: []string{"s1"},
		Generation: 1, SandboxId: sandboxID, ScratchBytes: scratchGiB << 30,
	}
}

// keyInit sets the key, as the node agent does at Create, then runs Init.
func keyInit(ctx context.Context, c pb.SandboxdClient, key string, r *pb.InitRequest) (*pb.InitResponse, error) {
	if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: key}); err != nil {
		return nil, err
	}
	r.HostTime = timestamppb.New(time.Now())
	return c.Init(keyed(ctx, key), r)
}

func keyed(ctx context.Context, key string) context.Context {
	return metadata.AppendToOutgoingContext(ctx, guestd.KeyHeader, key)
}

type result struct {
	id             string
	stdout, stderr string
	res            *pb.ExecResult
}

func collect(s interface {
	Recv() (*pb.ExecEvent, error)
}) (result, error) {
	var r result
	var out, errb strings.Builder
	for {
		ev, err := s.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			r.stdout, r.stderr = out.String(), errb.String()
			return r, err
		}
		switch x := ev.GetEvent().(type) {
		case *pb.ExecEvent_Started:
			r.id = x.Started.GetExecutionId()
		case *pb.ExecEvent_Output:
			if x.Output.GetStream() == pb.OutputStream_STDOUT {
				out.Write(x.Output.GetData())
			} else {
				errb.Write(x.Output.GetData())
			}
		case *pb.ExecEvent_Result:
			r.res = x.Result
		}
	}
	r.stdout, r.stderr = out.String(), errb.String()
	if r.res == nil {
		return r, errors.New("no result event")
	}
	return r, nil
}

func run(ctx context.Context, c pb.SandboxdClient, cmd *pb.Command) (result, error) {
	s, err := c.Run(ctx, &pb.RunRequest{Command: cmd})
	if err != nil {
		return result{}, err
	}
	return collect(s)
}

func sh(script string) *pb.Command { return &pb.Command{Argv: []string{"sh", "-c", script}} }

func pct(v []float64, p float64) float64 {
	if len(v) == 0 {
		return 0
	}
	s := slices.Clone(v)
	slices.Sort(s)
	i := int(p*float64(len(s)-1) + 0.5)
	return s[i]
}

func ms(d time.Duration) float64 { return float64(d.Microseconds()) / 1000 }
