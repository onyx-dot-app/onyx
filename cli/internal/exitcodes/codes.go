// Package exitcodes defines semantic exit codes for the Onyx CLI.
package exitcodes

import "fmt"

const (
	Success        = 0
	General        = 1
	NotConfigured  = 2
	AuthFailure    = 3
	Unreachable    = 4
	BadRequest     = 5
)

// ExitError wraps an error with a specific exit code.
type ExitError struct {
	Code int
	Err  error
}

func (e *ExitError) Error() string {
	return e.Err.Error()
}

func (e *ExitError) Unwrap() error {
	return e.Err
}

// New creates an ExitError with the given code and message.
func New(code int, msg string) *ExitError {
	return &ExitError{Code: code, Err: fmt.Errorf("%s", msg)}
}

// Wrap creates an ExitError wrapping an existing error.
func Wrap(code int, err error) *ExitError {
	return &ExitError{Code: code, Err: err}
}

// Newf creates an ExitError with a formatted message.
func Newf(code int, format string, args ...any) *ExitError {
	return &ExitError{Code: code, Err: fmt.Errorf(format, args...)}
}
