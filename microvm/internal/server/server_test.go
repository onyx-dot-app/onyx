package server

import (
	"context"
	"io"
	"log/slog"
	"path/filepath"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

type noLaunch struct{}

func (noLaunch) Launch(context.Context, agent.LaunchSpec) (agent.Process, error) {
	return nil, apierr.New(pb.ErrorReason_VMM_FAILED, "not in this test")
}

type stats struct{}

func (stats) MemInfo() (uint64, uint64, error) { return 1024, 512, nil }
func (stats) DiskFreeBytes() (uint64, error)   { return 1 << 40, nil }

// TestTypedErrorsOverUnixSocket checks that a client gets the gRPC code and
// the ErrorInfo reason.
func TestTypedErrorsOverUnixSocket(t *testing.T) {
	uids, _ := jailer.NewUIDPool(1000, 10)
	m := agent.NewManager(agent.Config{StartTimeout: time.Second, StopTimeout: time.Second, MaxScratchGiB: 10},
		&template.Store{Dir: t.TempDir()}, noLaunch{}, stats{}, uids, agent.Versions{Firecracker: "v1.17.0", Agent: "test"},
		slog.New(slog.NewTextHandler(io.Discard, nil)))
	// Short path: macOS limits sun_path to 104 bytes.
	sock := filepath.Join("/tmp", "ha-"+filepath.Base(t.TempDir())+".sock")
	ln, err := ListenUnix(sock)
	if err != nil {
		t.Fatal(err)
	}
	srv := New(m)
	go func() { _ = srv.Serve(ln) }()
	defer srv.Stop()
	conn, err := grpc.NewClient("unix://"+sock, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	c := pb.NewHostAgentClient(conn)
	ctx := context.Background()

	_, err = c.Create(ctx, &pb.CreateRequest{SandboxId: "11111111-1111-4111-8111-111111111111", Attempt: 1, Template: "missing", Vcpus: 2, MemMib: 4096, ScratchGib: 1, TenantId: "public"})
	if status.Code(err) != codes.NotFound || apierr.FromStatus(err) != pb.ErrorReason_TEMPLATE_MISSING {
		t.Fatalf("create: code %s reason %s (%v)", status.Code(err), apierr.FromStatus(err), err)
	}
	_, err = c.Stop(ctx, &pb.StopRequest{SandboxId: "11111111-1111-4111-8111-111111111111", Attempt: 1, Generation: 1})
	if status.Code(err) != codes.NotFound || apierr.FromStatus(err) != pb.ErrorReason_SANDBOX_NOT_FOUND {
		t.Fatalf("stop: code %s reason %s (%v)", status.Code(err), apierr.FromStatus(err), err)
	}
	l, err := c.List(ctx, &pb.ListRequest{})
	if err != nil || len(l.GetVms()) != 0 {
		t.Fatalf("list: %v %v", l, err)
	}
	ni, err := c.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err != nil || ni.GetMemAvailableMib() != 512 || ni.GetFirecrackerVersion() != "v1.17.0" {
		t.Fatalf("node info: %v %v", ni, err)
	}
}

func TestEveryReasonHasACode(t *testing.T) {
	for v, name := range pb.ErrorReason_name {
		r := pb.ErrorReason(v)
		if r == pb.ErrorReason_ERROR_REASON_UNSPECIFIED {
			continue
		}
		st := apierr.Status(apierr.New(r, "x"))
		if apierr.FromStatus(st.Err()) != r {
			t.Errorf("%s does not round-trip", name)
		}
		if st.Code() == codes.OK || st.Code() == codes.Unknown {
			t.Errorf("%s maps to %s", name, st.Code())
		}
	}
}

func TestBuildTemplateAndTemplateInfo(t *testing.T) {
	dir := t.TempDir()
	if _, err := template.WriteFake(dir, "v5.1.0-0123456789ab", template.Key{
		ImageRef: "onyxdotapp/sandbox:v5.1.0", VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, FirecrackerVersion: "v1.17.0", CPUModel: "cpu-a",
	}); err != nil {
		t.Fatal(err)
	}
	store := &template.Store{Dir: dir}
	uids, _ := jailer.NewUIDPool(1000, 10)
	m := agent.NewManager(agent.Config{StartTimeout: time.Second, StopTimeout: time.Second, MaxScratchGiB: 10},
		store, noLaunch{}, stats{}, uids, agent.Versions{Firecracker: "v1.17.0", CPUModel: "cpu-b"},
		slog.New(slog.NewTextHandler(io.Discard, nil)))
	svc := &Service{M: m}
	ctx := context.Background()
	_, err := svc.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if apierr.FromStatus(err) != pb.ErrorReason_INVALID_ARGUMENT {
		t.Fatalf("no --rootfs-dir: %v", err)
	}
	svc.Builder = func(context.Context) (tplbuild.Result, error) {
		tpl, err := store.Get("v5.1.0-0123456789ab")
		return tplbuild.Result{Template: tpl, Built: true, BuildMS: 1234, Removed: []string{"old"}}, err
	}
	r, err := svc.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil {
		t.Fatal(err)
	}
	ti := r.GetTemplate()
	if !r.GetBuilt() || r.GetBuildMs() != 1234 || len(r.GetRemoved()) != 1 || ti.GetImageRef() != "onyxdotapp/sandbox:v5.1.0" ||
		len(ti.GetKeySha256()) != 64 || len(ti.GetRootfsSha256()) != 64 || ti.GetBuiltAt() == nil {
		t.Fatalf("response %v", r)
	}
	// The template was built on another CPU model: NodeInfo lists it as not compatible.
	if ti.GetCompatible() {
		t.Fatal("a template of another CPU model is compatible")
	}
	ni, err := svc.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err != nil || len(ni.GetTemplates()) != 1 || ni.GetTemplates()[0].GetCompatible() {
		t.Fatalf("node info %v %v", ni, err)
	}
}
