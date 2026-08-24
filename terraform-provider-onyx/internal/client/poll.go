package client

import (
	"context"
	"fmt"
	"time"
)

// Defaults for the convergence polls. Several Onyx writes only schedule work
// for Celery, so the API answers long before the change is real.
const (
	pollInitialInterval = 2 * time.Second
	pollMaxInterval     = 15 * time.Second
)

// pollSettings is the knob set the tests drive directly.
type pollSettings struct {
	timeout         time.Duration
	initialInterval time.Duration
	maxInterval     time.Duration
}

// TimeoutError reports that a background operation did not finish in time.
// The operation is usually still running, so the message says so rather than
// implying the request failed.
type TimeoutError struct {
	Operation string
	Timeout   time.Duration
	// LastState describes what the final poll saw, when the caller knows.
	LastState string
}

func (e *TimeoutError) Error() string {
	msg := fmt.Sprintf("timed out after %s waiting for %s", e.Timeout, e.Operation)
	if e.LastState != "" {
		msg += ": " + e.LastState
	}
	return msg + ". The operation runs in the background and may still finish; " +
		"check the Onyx admin panel, and raise the timeout if this deployment is slow"
}

// Poll calls check until it reports done, it returns an error, the context
// ends, or timeout elapses. The first check runs immediately, then the
// interval backs off so a slow operation does not hammer the API.
//
// check may set lastState to describe what it saw; the timeout error carries
// the most recent value.
func Poll(
	ctx context.Context,
	timeout time.Duration,
	operation string,
	check func(ctx context.Context) (done bool, lastState string, err error),
) error {
	return pollWith(ctx, pollSettings{
		timeout:         timeout,
		initialInterval: pollInitialInterval,
		maxInterval:     pollMaxInterval,
	}, operation, check)
}

func pollWith(
	ctx context.Context,
	settings pollSettings,
	operation string,
	check func(ctx context.Context) (done bool, lastState string, err error),
) error {
	// Keep the caller's context: when Terraform cancels the run, both it and
	// the derived one report Done, and only the caller's says why.
	caller := ctx
	ctx, cancel := context.WithTimeout(caller, settings.timeout)
	defer cancel()

	interval := settings.initialInterval
	lastState := ""
	for {
		done, state, err := check(ctx)
		if err != nil {
			if callerErr := caller.Err(); callerErr != nil {
				return callerErr
			}
			// A check cancelled by our own deadline is a timeout, not a
			// transport failure; report it as one.
			if ctx.Err() != nil {
				return &TimeoutError{Operation: operation, Timeout: settings.timeout, LastState: lastState}
			}
			return err
		}
		if done {
			return nil
		}
		if state != "" {
			lastState = state
		}

		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			if callerErr := caller.Err(); callerErr != nil {
				return callerErr
			}
			return &TimeoutError{Operation: operation, Timeout: settings.timeout, LastState: lastState}
		case <-timer.C:
		}

		if interval < settings.maxInterval {
			interval *= 2
			if interval > settings.maxInterval {
				interval = settings.maxInterval
			}
		}
	}
}
