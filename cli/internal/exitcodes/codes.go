// Package exitcodes defines semantic exit codes for the Onyx CLI.
package exitcodes

import "fmt"

const (
	Success       = 0
	General       = 1
	BadRequest    = 2 // invalid args / command-line errors (convention)
	NotConfigured = 3
	AuthFailure   = 4
	Unreachable   = 5
)

// ExitError wraps an error with a specific exit code.
type ExitError struct {
	Code int
	Err  error
}

func (e *ExitError) Error() string {
	return e.Err.Error()
}

// New creates an ExitError with the given code and message.
func New(code int, msg string) *ExitError {
	return &ExitError{Code: code, Err: fmt.Errorf("%s", msg)}
}

// Newf creates an ExitError with a formatted message.
func Newf(code int, format string, args ...any) *ExitError {
	return &ExitError{Code: code, Err: fmt.Errorf(format, args...)}
}
