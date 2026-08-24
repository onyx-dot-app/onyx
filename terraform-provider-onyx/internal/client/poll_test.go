package client

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

// fastPoll keeps the backoff shape but shrinks it so tests stay quick.
func fastPoll(timeout time.Duration) pollSettings {
	return pollSettings{
		timeout:         timeout,
		initialInterval: time.Millisecond,
		maxInterval:     2 * time.Millisecond,
	}
}

func TestPollReturnsOnceDone(t *testing.T) {
	calls := 0
	err := pollWith(context.Background(), fastPoll(time.Second), "the thing", func(context.Context) (bool, string, error) {
		calls++
		return calls == 3, "still working", nil
	})
	if err != nil {
		t.Fatalf("expected success, got %v", err)
	}
	if calls != 3 {
		t.Errorf("check ran %d times, want 3", calls)
	}
}

func TestPollChecksImmediately(t *testing.T) {
	// A zero timeout must still allow one check, so an already-finished
	// operation never reports a timeout.
	calls := 0
	err := pollWith(context.Background(), fastPoll(0), "the thing", func(context.Context) (bool, string, error) {
		calls++
		return true, "", nil
	})
	if err != nil {
		t.Fatalf("expected success, got %v", err)
	}
	if calls != 1 {
		t.Errorf("check ran %d times, want 1", calls)
	}
}

func TestPollTimesOutWithLastState(t *testing.T) {
	err := pollWith(context.Background(), fastPoll(20*time.Millisecond), "deletion to finish", func(context.Context) (bool, string, error) {
		return false, "status is DELETING", nil
	})
	var timeoutErr *TimeoutError
	if !errors.As(err, &timeoutErr) {
		t.Fatalf("expected *TimeoutError, got %T: %v", err, err)
	}
	if timeoutErr.Operation != "deletion to finish" || timeoutErr.LastState != "status is DELETING" {
		t.Errorf("unexpected timeout error: %+v", timeoutErr)
	}
	if !strings.Contains(err.Error(), "may still finish") {
		t.Errorf("timeout message should say the operation continues: %s", err.Error())
	}
}

func TestPollPropagatesCheckError(t *testing.T) {
	sentinel := errors.New("boom")
	err := pollWith(context.Background(), fastPoll(time.Second), "the thing", func(context.Context) (bool, string, error) {
		return false, "", sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Fatalf("expected the check error, got %v", err)
	}
}

func TestPollRespectsCallerCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := pollWith(ctx, fastPoll(time.Second), "the thing", func(ctx context.Context) (bool, string, error) {
		return false, "", ctx.Err()
	})
	var timeoutErr *TimeoutError
	if !errors.As(err, &timeoutErr) {
		t.Fatalf("expected a timeout error for a cancelled context, got %T: %v", err, err)
	}
}
