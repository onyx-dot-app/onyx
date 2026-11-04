// Package server serves the HostAgent gRPC API.
package server

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"syscall"

	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// Service adapts an agent.Manager to the gRPC API.
type Service struct {
	pb.UnimplementedHostAgentServer
	M *agent.Manager
}

// Create implements pb.HostAgentServer.
func (s *Service) Create(ctx context.Context, r *pb.CreateRequest) (*pb.CreateResponse, error) {
	vm, created, err := s.M.Create(ctx, agent.CreateRequest{
		SandboxID: r.GetSandboxId(), Attempt: r.GetAttempt(), Template: r.GetTemplate(),
		VCPUs: r.GetVcpus(), MemMiB: r.GetMemMib(), ScratchGiB: r.GetScratchGib(),
	})
	if err != nil {
		return nil, toStatus(err)
	}
	return &pb.CreateResponse{Vm: toVM(vm), Created: created}, nil
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
		out.Templates = append(out.Templates, &pb.TemplateInfo{
			Version: t.Version, Vcpus: t.VCPUs, MemMib: t.MemMiB, ScratchGib: t.ScratchGiB,
			GuestKernel: t.GuestKernel, FirecrackerVersion: t.FirecrackerVersion,
		})
	}
	return out, nil
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
		Vcpus: vm.VCPUs, MemMib: vm.MemMiB, ScratchGib: vm.ScratchGiB, State: vm.State,
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
	s := grpc.NewServer(opts...)
	pb.RegisterHostAgentServer(s, &Service{M: m})
	return s
}
