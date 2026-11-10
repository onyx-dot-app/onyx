package server

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/managed"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// slotOps is a small guest kernel: slot A mounted, slot B behind a drive
// whose UUID the test sets.
type slotOps struct {
	mu     sync.Mutex
	top    string
	uuid   map[string]string
	inUse  map[string]bool
	mounts int
}

func (o *slotOps) Probe(dev string) (guestd.DevState, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	rdev := map[string]uint64{"/dev/vdc": 1, "/dev/vdf": 2}[dev]
	return guestd.DevState{Present: true, Rdev: rdev, Size: 1 << 20, UUID: o.uuid[dev], InUse: o.inUse[dev] || o.top == dev}, nil
}

func (o *slotOps) MountedDev(string) (uint64, bool, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return map[string]uint64{"/dev/vdc": 1, "/dev/vdf": 2}[o.top], true, nil
}
func (o *slotOps) WaitSize(context.Context, string, uint64) error { return nil }
func (o *slotOps) Flush(string) error                             { return nil }
func (o *slotOps) Mount(dev, _ string, _ bool) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.mounts++
	o.top = dev
	return nil
}
func (o *slotOps) DetachTop(string) error                 { return nil }
func (o *slotOps) MountedOn(string, uint64) (bool, error) { return false, nil }

func initDirect(t *testing.T, uds string) {
	t.Helper()
	conn, err := grpc.NewClient("passthrough:///vm", grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) { return fcvm.DialVsock(ctx, uds, 52) }))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	c := sdpb.NewSandboxdClient(conn)
	if _, err := c.SetKey(context.Background(), &sdpb.SetKeyRequest{Key: vmKey}); err != nil {
		t.Fatal(err)
	}
	_, err = c.Init(metadata.AppendToOutgoingContext(context.Background(), "x-sandboxd-key", vmKey), &sdpb.InitRequest{
		HostTime: timestamppb.Now(), Entropy: make([]byte, 32),
	})
	if err != nil {
		t.Fatal(err)
	}
}

// DaemonManaged calls the real guest daemon over the vsock handshake and
// maps its errors to host agent reasons.
func TestDaemonManagedOverVsock(t *testing.T) {
	ops := &slotOps{top: "/dev/vdc", uuid: map[string]string{"/dev/vdc": "", "/dev/vdf": ""}, inUse: map[string]bool{}}
	vm := startFakeVMWith(t, guestd.Config{Version: "test", Managed: &guestd.ManagedConfig{
		MountPoint: "/workspace/managed", Ops: ops,
		Devices: map[sdpb.ManagedSlot]string{sdpb.ManagedSlot_MANAGED_SLOT_A: "/dev/vdc", sdpb.ManagedSlot_MANAGED_SLOT_B: "/dev/vdf"},
	}})
	d := DaemonManaged{}
	tgt := agent.GuestTarget{VsockUDS: vm.uds, Generation: 1}
	ctx := context.Background()

	if _, err := d.Status(ctx, tgt, vmKey); apierr.ReasonOf(err) != pb.ErrorReason_GUEST_KEY_REJECTED {
		t.Fatalf("before SetKey: %v", err)
	}
	initDirect(t, vm.uds)
	if _, err := d.Status(ctx, tgt, "wrong-key-wrong-key-wrong-key-xx"); apierr.ReasonOf(err) != pb.ErrorReason_GUEST_KEY_REJECTED {
		t.Fatalf("wrong key: %v", err)
	}
	st, err := d.Status(ctx, tgt, vmKey)
	if err != nil || st.Active != pb.ManagedSlot_MANAGED_SLOT_A || !st.Slots[pb.ManagedSlot_MANAGED_SLOT_A].InUse ||
		st.Slots[pb.ManagedSlot_MANAGED_SLOT_B].InUse || !st.Slots[pb.ManagedSlot_MANAGED_SLOT_B].Present {
		t.Fatalf("status %+v %v", st, err)
	}
	uuid := managed.UUIDFor(string(bytes.Repeat([]byte("a"), 64)))
	ops.mu.Lock()
	ops.uuid["/dev/vdf"] = uuid
	ops.mu.Unlock()
	mr, err := d.Mount(ctx, tgt, vmKey, pb.ManagedSlot_MANAGED_SLOT_B, 1<<20, uuid)
	if err != nil || mr.Active != pb.ManagedSlot_MANAGED_SLOT_B || !mr.Changed {
		t.Fatalf("mount %+v %v", mr, err)
	}
	// Slot A still has readers: busy.
	ops.mu.Lock()
	ops.inUse["/dev/vdc"] = true
	ops.mu.Unlock()
	if _, err := d.Mount(ctx, tgt, vmKey, pb.ManagedSlot_MANAGED_SLOT_A, 1<<20, uuid); apierr.ReasonOf(err) != pb.ErrorReason_MANAGED_SLOT_BUSY {
		t.Fatalf("busy: %v", err)
	}
	// A wrong UUID is a failed mount.
	ops.mu.Lock()
	ops.inUse["/dev/vdc"] = false
	ops.mu.Unlock()
	if _, err := d.Mount(ctx, tgt, vmKey, pb.ManagedSlot_MANAGED_SLOT_A, 1<<20, uuid); apierr.ReasonOf(err) != pb.ErrorReason_MANAGED_MOUNT_FAILED {
		t.Fatalf("wrong uuid: %v", err)
	}

	// A daemon without managed slots (an older root drive).
	old := startFakeVM(t)
	initDirect(t, old.uds)
	if _, err := d.Status(ctx, agent.GuestTarget{VsockUDS: old.uds}, vmKey); apierr.ReasonOf(err) != pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED {
		t.Fatalf("old daemon: %v", err)
	}
	// Nothing listens.
	if _, err := d.Status(ctx, agent.GuestTarget{VsockUDS: filepath.Join(t.TempDir(), "none.sock")}, vmKey); apierr.ReasonOf(err) != pb.ErrorReason_GUEST_UNREACHABLE {
		t.Fatalf("no VM: %v", err)
	}
	if ops.mounts != 1 {
		t.Fatalf("%d mounts", ops.mounts)
	}
}

func bundle(t *testing.T) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	w, err := zw.Create("skills/pdf/SKILL.md")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = w.Write([]byte("# pdf"))
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func fakeMkfs(_ context.Context, path, _ string, size int64, _ string, _ int) error {
	return os.WriteFile(path, make([]byte, size), 0o600)
}

// PutManagedImage streams a zip; SwapManaged checks its request.
func TestManagedImageAPI(t *testing.T) {
	uids, _ := jailer.NewUIDPool(1000, 10)
	m := agent.NewManager(agent.Config{StartTimeout: time.Second, StopTimeout: time.Second, MaxScratchGiB: 10},
		&template.Store{Dir: t.TempDir()}, noLaunch{}, stats{}, uids, agent.Versions{Firecracker: "v1.17.0"},
		slog.New(slog.NewTextHandler(io.Discard, nil)))
	store := &managed.Store{Dir: t.TempDir(), Limits: managed.DefaultLimits, Mkfs: fakeMkfs}
	svc := &Service{M: m, Managed: &ManagedImages{Store: store, Keep: 2}}
	sock := filepath.Join("/tmp", "mi-"+filepath.Base(t.TempDir())+".sock")
	ln, err := ListenUnix(sock)
	if err != nil {
		t.Fatal(err)
	}
	srv := NewServer(svc)
	go func() { _ = srv.Serve(ln) }()
	defer srv.Stop()
	conn, err := grpc.NewClient("unix://"+sock, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	c := pb.NewHostAgentClient(conn)
	ctx := context.Background()

	z := bundle(t)
	sum := sha256.Sum256(z)
	id := hex.EncodeToString(sum[:])
	put := func(hdr *pb.ManagedBundleHeader, chunks ...[]byte) (*pb.PutManagedImageResponse, error) {
		s, err := c.PutManagedImage(ctx)
		if err != nil {
			return nil, err
		}
		if hdr != nil {
			if err := s.Send(&pb.PutManagedImageRequest{Part: &pb.PutManagedImageRequest_Header{Header: hdr}}); err != nil {
				return nil, err
			}
		}
		for _, ch := range chunks {
			if err := s.Send(&pb.PutManagedImageRequest{Part: &pb.PutManagedImageRequest_Data{Data: ch}}); err != nil {
				break
			}
		}
		return s.CloseAndRecv()
	}
	if _, err := put(nil, z); apierr.FromStatus(err) != pb.ErrorReason_INVALID_ARGUMENT {
		t.Fatalf("no header: %v", err)
	}
	if _, err := put(&pb.ManagedBundleHeader{Sha256: id, SizeBytes: uint64(len(z))}, z[:10]); apierr.FromStatus(err) != pb.ErrorReason_MANAGED_BUNDLE_INVALID {
		t.Fatalf("short: %v", err)
	}
	r, err := put(&pb.ManagedBundleHeader{Sha256: id, SizeBytes: uint64(len(z))}, z[:7], z[7:])
	if err != nil || !r.GetBuilt() || r.GetImage().GetImageId() != id || r.GetImage().GetFsUuid() != managed.UUIDFor(id) || r.GetImage().GetFiles() != 1 {
		t.Fatalf("put %v %v", r, err)
	}
	// Again: already there, no body needed.
	r, err = put(&pb.ManagedBundleHeader{Sha256: id, SizeBytes: uint64(len(z))})
	if err != nil || r.GetBuilt() {
		t.Fatalf("repeat put %v %v", r, err)
	}
	ni, err := c.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err != nil || len(ni.GetManagedImages()) != 1 || ni.GetManagedImages()[0].GetImageId() != id {
		t.Fatalf("node info %v %v", ni, err)
	}

	tgt := &pb.SwapTarget{SandboxId: "11111111-1111-4111-8111-111111111111", Attempt: 1, Generation: 1, SandboxdKey: vmKey}
	for name, c2 := range map[string]struct {
		req  *pb.SwapManagedRequest
		want pb.ErrorReason
	}{
		"no targets":    {&pb.SwapManagedRequest{ImageId: id}, pb.ErrorReason_INVALID_ARGUMENT},
		"twice":         {&pb.SwapManagedRequest{ImageId: id, Targets: []*pb.SwapTarget{tgt, tgt}}, pb.ErrorReason_INVALID_ARGUMENT},
		"no key":        {&pb.SwapManagedRequest{ImageId: id, Targets: []*pb.SwapTarget{{SandboxId: tgt.SandboxId}}}, pb.ErrorReason_INVALID_ARGUMENT},
		"missing image": {&pb.SwapManagedRequest{ImageId: string(bytes.Repeat([]byte("0"), 64)), Targets: []*pb.SwapTarget{tgt}}, pb.ErrorReason_MANAGED_IMAGE_MISSING},
	} {
		if _, err := c.SwapManaged(ctx, c2.req); apierr.FromStatus(err) != c2.want {
			t.Errorf("%s: %v", name, err)
		}
	}
	// A VM that is not on the node: a per-target result, not a call error.
	sr, err := c.SwapManaged(metadata.NewOutgoingContext(ctx, nil), &pb.SwapManagedRequest{ImageId: id, Targets: []*pb.SwapTarget{tgt}})
	if err != nil || len(sr.GetResults()) != 1 || sr.GetResults()[0].GetOk() || sr.GetResults()[0].GetReason() != pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED {
		t.Fatalf("swap %v %v", sr, err)
	}
	m.UseManagedGuest(DaemonManaged{}, time.Second)
	sr, err = c.SwapManaged(ctx, &pb.SwapManagedRequest{ImageId: id, Targets: []*pb.SwapTarget{tgt}})
	if err != nil || sr.GetResults()[0].GetReason() != pb.ErrorReason_SANDBOX_NOT_FOUND || sr.GetResults()[0].GetMessage() == "" {
		t.Fatalf("swap %v %v", sr, err)
	}
}
