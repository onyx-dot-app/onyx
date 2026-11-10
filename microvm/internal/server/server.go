// Package server serves the HostAgent gRPC API.
package server

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sync"
	"syscall"

	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// KeyInstaller sets the guest daemon key of a running VM.
type KeyInstaller interface {
	InstallKey(ctx context.Context, vm agent.VM, key string) error
}

// Service adapts an agent.Manager to the gRPC API.
type Service struct {
	pb.UnimplementedHostAgentServer
	M *agent.Manager
	// DialPorts are the guest ports Dial allows. Nil means DefaultDialPorts.
	// Dial refuses DaemonPort even if it is listed here.
	DialPorts []uint32
	// Builder builds the node template from --rootfs-dir. Nil: the
	// agent has no root drive to build from.
	Builder func(ctx context.Context) (tplbuild.Result, error)
	// DaemonPort is the guest daemon's vsock port. 0 means DefaultDaemonPort.
	DaemonPort uint32
	// MaxDialsPerVM caps the open Dial streams of one VM. 0 means
	// DefaultMaxDialsPerVM.
	MaxDialsPerVM int
	// Keys installs CreateRequest.sandboxd_key. Nil ignores the key.
	Keys KeyInstaller

	dialMu sync.Mutex
	dials  map[string]int
}

// Create implements pb.HostAgentServer.
func (s *Service) Create(ctx context.Context, r *pb.CreateRequest) (*pb.CreateResponse, error) {
	key := r.GetSandboxdKey()
	if err := validateDaemonKey(key); err != nil {
		return nil, toStatus(apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandboxd_key: %v", err))
	}
	vm, created, err := s.M.Create(ctx, agent.CreateRequest{
		SandboxID: r.GetSandboxId(), Attempt: r.GetAttempt(), Template: r.GetTemplate(),
		VCPUs: r.GetVcpus(), MemMiB: r.GetMemMib(), ScratchGiB: r.GetScratchGib(), TenantID: r.GetTenantId(),
	})
	if err != nil {
		return nil, toStatus(err)
	}
	if key != "" && s.Keys != nil && vm.State == pb.VMState_VM_STATE_RUNNING {
		if err := s.Keys.InstallKey(ctx, vm, key); err != nil {
			return nil, toStatus(err)
		}
	}
	return &pb.CreateResponse{Vm: toVM(vm), Created: created}, nil
}

// validateDaemonKey applies the daemon's SetKey rules, so that a bad key
// fails before a VM starts. Empty means no key.
func validateDaemonKey(key string) error {
	if key == "" {
		return nil
	}
	if n := len(key); n < 32 || n > 512 {
		return fmt.Errorf("must be 32 to 512 bytes, got %d", n)
	}
	for _, c := range []byte(key) {
		if c <= ' ' || c > '~' {
			return errors.New("must be printable ASCII with no spaces")
		}
	}
	return nil
}

// Stop implements pb.HostAgentServer.
func (s *Service) Stop(ctx context.Context, r *pb.StopRequest) (*pb.StopResponse, error) {
	res, err := s.M.Stop(ctx, r.GetSandboxId(), r.GetAttempt(), r.GetGeneration())
	if err != nil {
		return nil, toStatus(err)
	}
	return &pb.StopResponse{AlreadyStopped: res.AlreadyStopped}, nil
}

// List implements pb.HostAgentServer.
func (s *Service) List(context.Context, *pb.ListRequest) (*pb.ListResponse, error) {
	vms := s.M.List()
	out := &pb.ListResponse{Vms: make([]*pb.VM, 0, len(vms))}
	for _, vm := range vms {
		out.Vms = append(out.Vms, toVM(vm))
	}
	return out, nil
}

// CloseConnections implements pb.HostAgentServer.
func (s *Service) CloseConnections(_ context.Context, r *pb.CloseConnectionsRequest) (*pb.CloseConnectionsResponse, error) {
	n, err := s.M.CloseConnections(r.GetSandboxId(), r.GetAttempt(), r.GetGeneration())
	if err != nil {
		return nil, toStatus(err)
	}
	return &pb.CloseConnectionsResponse{Closed: uint32(n)}, nil
}

// NodeInfo implements pb.HostAgentServer.
func (s *Service) NodeInfo(context.Context, *pb.NodeInfoRequest) (*pb.NodeInfoResponse, error) {
	n, err := s.M.NodeInfo()
	if err != nil {
		return nil, toStatus(err)
	}
	out := &pb.NodeInfoResponse{
		MemTotalMib: n.MemTotalMiB, MemAvailableMib: n.MemAvailableMiB, DiskFreeMib: n.DiskFreeMiB,
		VmCount: uint32(n.VMCount), CpuModel: n.Versions.CPUModel, FirecrackerVersion: n.Versions.Firecracker,
		HostKernel: n.Versions.HostKernel, AgentVersion: n.Versions.Agent,
	}
	for _, t := range n.Templates {
		out.Templates = append(out.Templates, toTemplateInfo(t, n.Versions.NodeKey()))
	}
	return out, nil
}

// BuildTemplate implements pb.HostAgentServer.
func (s *Service) BuildTemplate(ctx context.Context, _ *pb.BuildTemplateRequest) (*pb.BuildTemplateResponse, error) {
	if s.Builder == nil {
		return nil, toStatus(apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "the agent has no --rootfs-dir to build a template from"))
	}
	r, err := s.Builder(ctx)
	if err != nil {
		return nil, toStatus(err)
	}
	return &pb.BuildTemplateResponse{
		Template: toTemplateInfo(r.Template, s.M.Versions().NodeKey()), Built: r.Built,
		BuildMs: uint64(r.BuildMS), Removed: r.Removed,
	}, nil
}

func toTemplateInfo(t *template.Template, node template.NodeKey) *pb.TemplateInfo {
	return &pb.TemplateInfo{
		Version: t.Version, Vcpus: t.VCPUs, MemMib: t.MemMiB, ScratchGib: t.ScratchGiB,
		GuestKernel: t.GuestKernel, FirecrackerVersion: t.FirecrackerVersion,
		ImageRef: t.ImageRef, ImageDigest: t.ImageDigest, RootfsSha256: t.RootfsSHA256, KeySha256: t.KeySHA256,
		CaFingerprint: t.CAFingerprint, BuiltAt: timestamppb.New(t.BuiltAt), Compatible: t.CheckNode(node) == nil,
	}
}

func toStatus(err error) error {
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	return apierr.Status(err).Err()
}

func toVM(vm agent.VM) *pb.VM {
	return &pb.VM{
		SandboxId: vm.SandboxID, Attempt: vm.Attempt, Generation: vm.Generation, Template: vm.Template,
		Vcpus: vm.VCPUs, MemMib: vm.MemMiB, ScratchGib: vm.ScratchGiB, State: vm.State, TenantId: vm.TenantID,
		Pid: int32(vm.PID), Uid: vm.UID, StartedAt: timestamppb.New(vm.StartedAt),
	}
}

// ListenUnix listens on a Unix socket that only root can use. It replaces a
// stale socket file. Call it before other goroutines create files: it sets
// the process umask for a moment.
func ListenUnix(path string) (net.Listener, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	// The socket is born without group or other access, so no one else can
	// connect before the Chmod.
	old := syscall.Umask(0o077)
	ln, err := net.Listen("unix", path)
	syscall.Umask(old)
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(path, 0o600); err != nil {
		_ = ln.Close()
		return nil, fmt.Errorf("chmod %s: %w", path, err)
	}
	return ln, nil
}

// New returns a gRPC server with the HostAgent service.
func New(m *agent.Manager, opts ...grpc.ServerOption) *grpc.Server {
	return NewServer(&Service{M: m}, opts...)
}

// NewServer returns a gRPC server for svc.
func NewServer(svc *Service, opts ...grpc.ServerOption) *grpc.Server {
	s := grpc.NewServer(opts...)
	pb.RegisterHostAgentServer(s, svc)
	return s
}
