//go:build container

package containertest

import (
	"archive/tar"
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

func env(t *testing.T, name string) string {
	t.Helper()
	v := os.Getenv(name)
	if v == "" {
		t.Fatalf("%s is not set", name)
	}
	return v
}

func dial(t *testing.T) (pb.SandboxdClient, string) {
	t.Helper()
	caPEM, err := os.ReadFile(env(t, "SANDBOXD_CA"))
	if err != nil {
		t.Fatal(err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		t.Fatal("SANDBOXD_CA has no certificate")
	}
	rawKey, err := os.ReadFile(env(t, "SANDBOXD_KEY"))
	if err != nil {
		t.Fatal(err)
	}
	creds := credentials.NewTLS(&tls.Config{RootCAs: pool, ServerName: "localhost", MinVersion: tls.VersionTLS13})
	conn, err := grpc.NewClient("passthrough:///"+env(t, "SANDBOXD_ADDR"), grpc.WithTransportCredentials(creds))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return pb.NewSandboxdClient(conn), strings.TrimSpace(string(rawKey))
}

func run(ctx context.Context, t *testing.T, c pb.SandboxdClient, cmd *pb.Command) (string, *pb.ExecResult) {
	t.Helper()
	s, err := c.Run(ctx, &pb.RunRequest{Command: cmd})
	if err != nil {
		t.Fatal(err)
	}
	var out strings.Builder
	var res *pb.ExecResult
	for {
		ev, err := s.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatalf("run %v: %v", cmd.GetArgv(), err)
		}
		switch x := ev.GetEvent().(type) {
		case *pb.ExecEvent_Output:
			out.Write(x.Output.GetData())
		case *pb.ExecEvent_Result:
			res = x.Result
		}
	}
	if res == nil {
		t.Fatalf("run %v: no result", cmd.GetArgv())
	}
	return out.String(), res
}

func bash(session, script string) *pb.Command {
	return &pb.Command{Argv: []string{"bash", "-c", script}, SessionId: session}
}

func TestContainerDaemon(t *testing.T) {
	c, key := dial(t)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	h, err := c.Health(ctx, &pb.HealthRequest{}, grpc.WaitForReady(true))
	if err != nil {
		t.Fatal(err)
	}
	if !h.GetKeySet() || h.GetInitialized() {
		t.Fatalf("health before Init: %v", h)
	}
	if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: strings.Repeat("x", 32)}); err == nil {
		t.Fatal("SetKey replaced the key file key")
	}
	kctx := metadata.AppendToOutgoingContext(ctx, guestd.KeyHeader, key)
	ir, err := c.Init(kctx, &pb.InitRequest{
		HostTime: timestamppb.Now(), Entropy: make([]byte, 32), Generation: 1, SandboxId: "check",
		SessionIds: []string{"s1"}, Env: map[string]string{"FROM_INIT": "yes"},
	})
	if err != nil {
		t.Fatalf("Init: %v", err)
	}
	if ir.GetClockStep().AsDuration() != 0 || ir.GetEntropyCredited() || ir.GetAttached() {
		t.Fatalf("Init did VM steps: %v", ir)
	}

	out, res := run(kctx, t, c, bash("s1", `echo "$(id -u):$(id -g) $(pwd) $FROM_INIT"`))
	if res.GetExitCode() != 0 || strings.TrimSpace(out) != "1000:1000 /home/onyx/workspaces/s1 yes" {
		t.Fatalf("command: %q %v", out, res)
	}

	data := []byte("hello from the container check\n")
	ws, err := c.WriteFile(kctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Header{Header: &pb.WriteFileHeader{
		SessionId: "s1", Path: "out/a.txt", Size: int64(len(data)), MakeParents: true,
	}}}); err != nil {
		t.Fatal(err)
	}
	if err := ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Data{Data: data}}); err != nil {
		t.Fatal(err)
	}
	if _, err := ws.CloseAndRecv(); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	out, res = run(kctx, t, c, bash("s1", `stat -c %u out/a.txt; cat out/a.txt`))
	if res.GetExitCode() != 0 || out != "1000\n"+string(data) {
		t.Fatalf("written file: %q %v", out, res)
	}

	installSkill(kctx, t, c)
	out, res = run(kctx, t, c, bash("", `cat /var/lib/onyx/skills/check/SKILL.md`))
	if res.GetExitCode() != 0 || out != "# check\n" {
		t.Fatalf("skill: %q %v", out, res)
	}

	// The proxy port is closed in the check, so with the lockdown every
	// direct connection fails at once.
	if os.Getenv("SANDBOXD_LOCKDOWN") == "1" {
		out, res = run(kctx, t, c, bash("", `curl -sS --noproxy '*' --max-time 5 https://1.1.1.1 2>&1; echo "exit=$?"`))
		if strings.Contains(out, "exit=0") {
			t.Fatalf("direct egress worked under the lockdown: %q %v", out, res)
		}
	}
}

func installSkill(ctx context.Context, t *testing.T, c pb.SandboxdClient) {
	t.Helper()
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	body := []byte("# check\n")
	for _, h := range []*tar.Header{
		{Name: "check/", Typeflag: tar.TypeDir, Mode: 0o755},
		{Name: "check/SKILL.md", Typeflag: tar.TypeReg, Mode: 0o644, Size: int64(len(body))},
	} {
		if err := tw.WriteHeader(h); err != nil {
			t.Fatal(err)
		}
		if h.Typeflag == tar.TypeReg {
			if _, err := tw.Write(body); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(buf.Bytes())
	s, err := c.InstallSkill(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Send(&pb.InstallSkillRequest{Part: &pb.InstallSkillRequest_Header{Header: &pb.InstallSkillHeader{
		Name: "check", Version: "1", SizeBytes: int64(buf.Len()), Sha256: hex.EncodeToString(sum[:]),
	}}}); err != nil {
		t.Fatal(err)
	}
	if err := s.Send(&pb.InstallSkillRequest{Part: &pb.InstallSkillRequest_Data{Data: buf.Bytes()}}); err != nil {
		t.Fatal(err)
	}
	if r, err := s.CloseAndRecv(); err != nil || !r.GetInstalled() {
		t.Fatalf("InstallSkill: %v %v", r, err)
	}
}
