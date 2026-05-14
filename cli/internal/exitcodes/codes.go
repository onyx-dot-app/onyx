// Package exitcodes defines semantic exit codes for the Onyx CLI.
package exitcodes

import "fmt"

// Code is a typed exit code for the CLI.
type Code int

const (
	Success       Code = 0
	General       Code = 1
	BadRequest    Code = 2 // invalid args / command-line errors (convention)
	NotConfigured Code = 3
	AuthFailure   Code = 4
	Unreachable   Code = 5
	RateLimited   Code = 6
	Timeout       Code = 7
	ServerError   Code = 8
	NotAvailable  Code = 9
)

// ForHTTPStatus maps an HTTP status code to a CLI exit code.
func ForHTTPStatus(statusCode int) Code {
	switch {
	case statusCode >= 200 && statusCode < 300:
		return Success
	case statusCode == 400 || statusCode == 422:
		return BadRequest
	case statusCode == 401 || statusCode == 403:
		return AuthFailure
	case statusCode == 404:
		return NotAvailable
	case statusCode == 429:
		return RateLimited
	case statusCode == 408 || statusCode == 504:
		return Timeout
	case statusCode >= 500:
		return ServerError
	default:
		return General
	}
}

// ExitError wraps an error with a specific exit code.
type ExitError struct {
	Code Code
	Err  error
}

func (e *ExitError) Error() string {
	return e.Err.Error()
}

func (e *ExitError) Unwrap() error { return e.Err }

// New creates an ExitError with the given code and message.
func New(code Code, msg string) *ExitError {
	return &ExitError{Code: code, Err: fmt.Errorf("%s", msg)}
}

// Newf creates an ExitError with a formatted message.
func Newf(code Code, format string, args ...any) *ExitError {
	return &ExitError{Code: code, Err: fmt.Errorf(format, args...)}
}
