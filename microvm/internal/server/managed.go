package server

import (
	"context"
	"errors"
	"io"
	"net"
	"time"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/managed"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sbpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// maxSwapTargets caps the VMs of one SwapManaged call.
const maxSwapTargets = 1000

// DaemonManaged implements agent.ManagedGuest: it calls the guest daemon's
// ManagedStatus and MountManaged over vsock with the VM's key.
type DaemonManaged struct {
	// Port is the guest daemon's vsock port. 0 means DefaultDaemonPort.
	Port uint32
}

var _ agent.ManagedGuest = DaemonManaged{}

func (d DaemonManaged) call(ctx context.Context, t agent.GuestTarget, key string, f func(context.Context, sbpb.SandboxdClient) error) error {
	port := d.Port
	if port == 0 {
		port = DefaultDaemonPort
	}
	conn, err := grpc.NewClient("passthrough:///guest-daemon",
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
			dctx, cancel := context.WithTimeout(ctx, dialTimeout)
			defer cancel()
			return fcvm.DialVsock(dctx, t.VsockUDS, port)
		}),
	)
	if err != nil {
		return err
	}
	defer func() { _ = conn.Close() }()
	ctx = metadata.AppendToOutgoingContext(ctx, "x-sandboxd-key", key)
	return guestErr(f(ctx, sbpb.NewSandboxdClient(conn)))
}

// guestErr maps a guest daemon error to a host agent reason. The message
// keeps the daemon's text.
func guestErr(err error) error {
	if err == nil {
		return nil
	}
	st, ok := status.FromError(err)
	if !ok {
		return err
	}
	reason := ""
	for _, d := range st.Details() {
		if info, isInfo := d.(*errdetails.ErrorInfo); isInfo {
			reason = info.GetReason()
		}
	}
	msg := "guest daemon: " + st.Message()
	switch {
	case st.Code() == codes.Unimplemented:
		return apierr.New(pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED, "%s", msg)
	case reason == sbpb.ErrorReason_MANAGED_SLOT_BUSY.String():
		return apierr.New(pb.ErrorReason_MANAGED_SLOT_BUSY, "%s", msg)
	case reason == sbpb.ErrorReason_MANAGED_DEVICE_MISMATCH.String(), reason == sbpb.ErrorReason_MANAGED_MOUNT_FAILED.String():
		return apierr.New(pb.ErrorReason_MANAGED_MOUNT_FAILED, "%s", msg)
	case reason == sbpb.ErrorReason_UNAUTHENTICATED.String(), reason == sbpb.ErrorReason_KEY_NOT_SET.String():
		return apierr.New(pb.ErrorReason_GUEST_KEY_REJECTED, "%s (send the VM's sandboxd_key from Create)", msg)
	case reason == sbpb.ErrorReason_NOT_INITIALIZED.String():
		return apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "%s (swap after the daemon's Init)", msg)
	case st.Code() == codes.Unavailable:
		return apierr.New(pb.ErrorReason_GUEST_UNREACHABLE, "%s", msg)
	case st.Code() == codes.DeadlineExceeded || st.Code() == codes.Canceled:
		return err
	default:
		return apierr.New(pb.ErrorReason_MANAGED_MOUNT_FAILED, "%s", msg)
	}
}

var toAgentSlot = map[sbpb.ManagedSlot]pb.ManagedSlot{
	sbpb.ManagedSlot_MANAGED_SLOT_A: pb.ManagedSlot_MANAGED_SLOT_A,
	sbpb.ManagedSlot_MANAGED_SLOT_B: pb.ManagedSlot_MANAGED_SLOT_B,
}

func toGuestSlot(s pb.ManagedSlot) sbpb.ManagedSlot {
	for g, a := range toAgentSlot {
		if a == s {
			return g
		}
	}
	return sbpb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED
}

// Status implements agent.ManagedGuest.
func (d DaemonManaged) Status(ctx context.Context, t agent.GuestTarget, key string) (agent.GuestManaged, error) {
	out := agent.GuestManaged{Slots: map[pb.ManagedSlot]agent.GuestSlot{}}
	err := d.call(ctx, t, key, func(ctx context.Context, c sbpb.SandboxdClient) error {
		r, err := c.ManagedStatus(ctx, &sbpb.ManagedStatusRequest{})
		if err != nil {
			return err
		}
		out.Active = toAgentSlot[r.GetActive()]
		for _, s := range r.GetSlots() {
			out.Slots[toAgentSlot[s.GetSlot()]] = agent.GuestSlot{Present: s.GetPresent(), InUse: s.GetInUse(), UUID: s.GetFsUuid()}
		}
		return nil
	})
	return out, err
}

// Mount implements agent.ManagedGuest.
func (d DaemonManaged) Mount(ctx context.Context, t agent.GuestTarget, key string, slot pb.ManagedSlot, size uint64, uuid string) (agent.GuestMount, error) {
	var out agent.GuestMount
	err := d.call(ctx, t, key, func(ctx context.Context, c sbpb.SandboxdClient) error {
		r, err := c.MountManaged(ctx, &sbpb.MountManagedRequest{Slot: toGuestSlot(slot), SizeBytes: size, FsUuid: uuid})
		if err != nil {
			return err
		}
		out = agent.GuestMount{Active: toAgentSlot[r.GetActive()], Changed: r.GetChanged(), PreviousInUse: r.GetPreviousInUse()}
		return nil
	})
	return out, err
}

// ManagedImages are the managed drive images of the node, for the API.
type ManagedImages struct {
	Store *managed.Store
	// Keep is how many images GC keeps, plus the ones VMs use.
	Keep int
}

func (s *Service) managedStore() (*ManagedImages, error) {
	if s.Managed == nil || s.Managed.Store == nil {
		return nil, apierr.New(pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED, "the agent has no managed image store")
	}
	return s.Managed, nil
}

func (s *Service) gcManaged() []string {
	mi := s.Managed
	removed, err := mi.Store.GC(mi.Keep, s.M.ManagedImagesInUse)
	if err != nil {
		s.log().Error("managed image GC", "err", err)
	}
	if len(removed) > 0 {
		s.log().Info("managed image GC", "removed", removed, "keep", mi.Keep)
	}
	return removed
}

// bundleReader reads the data parts of a PutManagedImage stream.
type bundleReader struct {
	stream pb.HostAgent_PutManagedImageServer
	buf    []byte
}

func (r *bundleReader) Read(p []byte) (int, error) {
	for len(r.buf) == 0 {
		m, err := r.stream.Recv()
		if err != nil {
			return 0, err
		}
		if m.GetHeader() != nil {
			return 0, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "only the first message may carry a header")
		}
		r.buf = m.GetData()
	}
	n := copy(p, r.buf)
	r.buf = r.buf[n:]
	return n, nil
}

// PutManagedImage implements pb.HostAgentServer.
func (s *Service) PutManagedImage(stream pb.HostAgent_PutManagedImageServer) error {
	mi, err := s.managedStore()
	if err != nil {
		return toStatus(err)
	}
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	hdr := first.GetHeader()
	if hdr == nil {
		return toStatus(apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "the first message must be the header"))
	}
	img, built, err := mi.Store.Put(stream.Context(), hdr.GetSha256(), int64(hdr.GetSizeBytes()), &bundleReader{stream: stream})
	if err != nil {
		if errors.Is(err, managed.ErrBundle) {
			return toStatus(apierr.New(pb.ErrorReason_MANAGED_BUNDLE_INVALID, "%v", err))
		}
		return toStatus(err)
	}
	resp := &pb.PutManagedImageResponse{Image: s.imageInfo(img), Built: built}
	if built {
		resp.BuildMs = uint64(img.BuildMS)
	}
	resp.Removed = s.gcManaged()
	return stream.SendAndClose(resp)
}

func (s *Service) imageInfo(img managed.Image) *pb.ManagedImageInfo {
	n := 0
	for _, vm := range s.M.List() {
		if vm.Managed.A == img.ID || vm.Managed.B == img.ID {
			n++
		}
	}
	return &pb.ManagedImageInfo{
		ImageId: img.ID, ImageSha256: img.SHA256, SizeBytes: uint64(img.Size), FsUuid: img.UUID,
		Files: uint32(img.Files), ContentBytes: uint64(img.ContentBytes), BuiltAt: timestamppb.New(img.BuiltAt), Vms: uint32(n),
	}
}

// SwapManaged implements pb.HostAgentServer.
func (s *Service) SwapManaged(ctx context.Context, r *pb.SwapManagedRequest) (*pb.SwapManagedResponse, error) {
	mi, err := s.managedStore()
	if err != nil {
		return nil, toStatus(err)
	}
	if n := len(r.GetTargets()); n == 0 || n > maxSwapTargets {
		return nil, toStatus(apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "targets must have 1 to %d VMs, got %d", maxSwapTargets, n))
	}
	seen := map[string]bool{}
	targets := make([]agent.SwapTarget, 0, len(r.GetTargets()))
	for _, t := range r.GetTargets() {
		if seen[t.GetSandboxId()] {
			return nil, toStatus(apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandbox %s is in targets twice", t.GetSandboxId()))
		}
		seen[t.GetSandboxId()] = true
		if t.GetSandboxdKey() == "" {
			return nil, toStatus(apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandbox %s has no sandboxd_key", t.GetSandboxId()))
		}
		targets = append(targets, agent.SwapTarget{
			SandboxID: t.GetSandboxId(), Attempt: t.GetAttempt(), Generation: t.GetGeneration(), Key: t.GetSandboxdKey(),
		})
	}
	// The pin keeps GC away until every target recorded the image.
	unpin := mi.Store.Pin(r.GetImageId())
	defer unpin()
	img, err := mi.Store.Get(r.GetImageId())
	if err != nil {
		if errors.Is(err, managed.ErrMissing) {
			return nil, toStatus(apierr.New(pb.ErrorReason_MANAGED_IMAGE_MISSING, "%v", err))
		}
		return nil, toStatus(err)
	}
	results := s.M.SwapManaged(ctx, agent.ManagedImage{ID: img.ID, Path: img.Path, Size: uint64(img.Size), UUID: img.UUID}, targets)
	out := &pb.SwapManagedResponse{}
	for _, res := range results {
		sr := &pb.SwapResult{
			SandboxId: res.SandboxID, Ok: res.Err == nil, Active: res.Active, Changed: res.Changed,
			Ms: uint64(res.Took / time.Millisecond), PreviousInUse: res.PreviousInUse,
		}
		if res.Err != nil {
			st := apierr.Status(res.Err)
			sr.Reason, sr.Message = apierr.FromStatus(st.Err()), st.Message()
			if errors.Is(res.Err, context.Canceled) || errors.Is(res.Err, context.DeadlineExceeded) {
				sr.Reason = pb.ErrorReason_INTERNAL
			}
		}
		out.Results = append(out.Results, sr)
	}
	s.gcManaged()
	return out, nil
}

var _ io.Reader = (*bundleReader)(nil)
