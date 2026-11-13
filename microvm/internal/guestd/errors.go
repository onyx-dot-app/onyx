package guestd

import (
	"context"
	"errors"
	"fmt"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// ErrorDomain is the google.rpc.ErrorInfo domain of every daemon error.
const ErrorDomain = "sandboxd.craft.onyx.app"

func code(r pb.ErrorReason) codes.Code {
	switch r {
	case pb.ErrorReason_INVALID_ARGUMENT, pb.ErrorReason_START_FAILED, pb.ErrorReason_ARCHIVE_INVALID:
		return codes.InvalidArgument
	case pb.ErrorReason_NOT_INITIALIZED, pb.ErrorReason_STDIN_NOT_OPEN, pb.ErrorReason_EXECUTION_ENDED,
		pb.ErrorReason_KEY_NOT_SET, pb.ErrorReason_KEY_ALREADY_SET, pb.ErrorReason_MANAGED_SLOT_BUSY,
		pb.ErrorReason_MANAGED_DEVICE_MISMATCH:
		return codes.FailedPrecondition
	case pb.ErrorReason_UNAUTHENTICATED:
		return codes.Unauthenticated
	case pb.ErrorReason_EXECUTION_NOT_FOUND, pb.ErrorReason_FILE_NOT_FOUND:
		return codes.NotFound
	case pb.ErrorReason_FILE_EXISTS:
		return codes.AlreadyExists
	case pb.ErrorReason_TOO_MANY_EXECUTIONS, pb.ErrorReason_LIMIT_EXCEEDED, pb.ErrorReason_EXECUTION_CAP_REACHED:
		return codes.ResourceExhausted
	default:
		return codes.Internal
	}
}

// apiError returns a gRPC status with an ErrorInfo detail.
func apiError(r pb.ErrorReason, format string, args ...any) error {
	st := status.New(code(r), r.String()+": "+fmt.Sprintf(format, args...))
	if d, err := st.WithDetails(&errdetails.ErrorInfo{Reason: r.String(), Domain: ErrorDomain}); err == nil {
		st = d
	}
	return st.Err()
}

// execError maps an execs error to a gRPC status.
func execError(err error) error {
	var se *execs.StartError
	switch {
	case errors.Is(err, execs.ErrNotFound):
		return apiError(pb.ErrorReason_EXECUTION_NOT_FOUND, "%v", err)
	case errors.Is(err, execs.ErrBadArgument):
		return apiError(pb.ErrorReason_INVALID_ARGUMENT, "%v", err)
	case errors.Is(err, execs.ErrTooMany):
		return apiError(pb.ErrorReason_TOO_MANY_EXECUTIONS, "%v", err)
	case errors.Is(err, execs.ErrCapReached):
		return apiError(pb.ErrorReason_EXECUTION_CAP_REACHED, "%v", err)
	case errors.Is(err, execs.ErrStdinNotOpen):
		return apiError(pb.ErrorReason_STDIN_NOT_OPEN, "%v", err)
	case errors.Is(err, execs.ErrEnded):
		return apiError(pb.ErrorReason_EXECUTION_ENDED, "%v", err)
	case errors.As(err, &se):
		return apiError(pb.ErrorReason_START_FAILED, "%v", err)
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		// Keep the context's code (CANCELED or DEADLINE_EXCEEDED), and add
		// the ErrorInfo that every daemon error has.
		st := status.FromContextError(err)
		if d, derr := st.WithDetails(&errdetails.ErrorInfo{Reason: pb.ErrorReason_INTERNAL.String(), Domain: ErrorDomain}); derr == nil {
			st = d
		}
		return st.Err()
	default:
		return apiError(pb.ErrorReason_INTERNAL, "%v", err)
	}
}
