// Package apierr holds the typed errors of the host agent API.
package apierr

import (
	"errors"
	"fmt"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// Domain is the google.rpc.ErrorInfo domain of every host agent error.
const Domain = "hostagent.craft.onyx.app"

// Error is an API error with a reason that clients can act on.
type Error struct {
	Reason pb.ErrorReason
	Msg    string
	// Metadata goes to google.rpc.ErrorInfo.metadata, for example the
	// memory numbers of CAPACITY_MEMORY.
	Metadata map[string]string
}

func (e *Error) Error() string { return e.Reason.String() + ": " + e.Msg }

// New returns an Error with a formatted message.
func New(reason pb.ErrorReason, format string, args ...any) *Error {
	return &Error{Reason: reason, Msg: fmt.Sprintf(format, args...)}
}

// ReasonOf returns the reason of err, or INTERNAL if err is not an *Error.
func ReasonOf(err error) pb.ErrorReason {
	var e *Error
	if errors.As(err, &e) {
		return e.Reason
	}
	return pb.ErrorReason_INTERNAL
}

// Code maps a reason to its gRPC status code.
func Code(r pb.ErrorReason) codes.Code {
	switch r {
	case pb.ErrorReason_INVALID_ARGUMENT, pb.ErrorReason_TEMPLATE_SHAPE_MISMATCH,
		pb.ErrorReason_SCRATCH_TOO_SMALL, pb.ErrorReason_SCRATCH_TOO_LARGE, pb.ErrorReason_MANAGED_BUNDLE_INVALID:
		return codes.InvalidArgument
	case pb.ErrorReason_TEMPLATE_MISSING, pb.ErrorReason_SANDBOX_NOT_FOUND, pb.ErrorReason_MANAGED_IMAGE_MISSING:
		return codes.NotFound
	case pb.ErrorReason_TEMPLATE_INCOMPATIBLE, pb.ErrorReason_ATTEMPT_CONFLICT,
		pb.ErrorReason_STALE_ATTEMPT, pb.ErrorReason_INSTANCE_MISMATCH, pb.ErrorReason_SANDBOX_IN_DOUBT,
		pb.ErrorReason_VM_NOT_RUNNING, pb.ErrorReason_GUEST_KEY_REJECTED, pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED,
		pb.ErrorReason_MANAGED_SLOT_BUSY, pb.ErrorReason_NODE_DRAINING:
		return codes.FailedPrecondition
	case pb.ErrorReason_CAPACITY_MEMORY, pb.ErrorReason_CAPACITY_DISK, pb.ErrorReason_CAPACITY_VM_SLOTS,
		pb.ErrorReason_DIAL_LIMIT:
		return codes.ResourceExhausted
	case pb.ErrorReason_PORT_NOT_ALLOWED, pb.ErrorReason_METHOD_NOT_ALLOWED:
		return codes.PermissionDenied
	case pb.ErrorReason_GUEST_UNREACHABLE:
		return codes.Unavailable
	default:
		return codes.Internal
	}
}

// Status converts err to a gRPC status with an ErrorInfo detail.
func Status(err error) *status.Status {
	var e *Error
	if !errors.As(err, &e) {
		e = &Error{Reason: pb.ErrorReason_INTERNAL, Msg: err.Error()}
	}
	st := status.New(Code(e.Reason), e.Msg)
	withInfo, detailErr := st.WithDetails(&errdetails.ErrorInfo{Reason: e.Reason.String(), Domain: Domain, Metadata: e.Metadata})
	if detailErr != nil {
		return st
	}
	return withInfo
}

// FromStatus returns the reason in a gRPC error, or ERROR_REASON_UNSPECIFIED.
func FromStatus(err error) pb.ErrorReason {
	st, ok := status.FromError(err)
	if !ok {
		return pb.ErrorReason_ERROR_REASON_UNSPECIFIED
	}
	for _, d := range st.Details() {
		info, isInfo := d.(*errdetails.ErrorInfo)
		if isInfo && info.GetDomain() == Domain {
			if v, known := pb.ErrorReason_value[info.GetReason()]; known {
				return pb.ErrorReason(v)
			}
		}
	}
	return pb.ErrorReason_ERROR_REASON_UNSPECIFIED
}
