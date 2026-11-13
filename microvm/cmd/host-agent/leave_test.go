package main

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
)

func TestLeaveDeregistersOnlyOnADrainingNode(t *testing.T) {
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	for name, tc := range map[string]struct {
		before, after []string
		err           error
		want          int
	}{
		"no taints":           {want: 0},
		"tainted":             {before: []string{"node.kubernetes.io/unschedulable=:NoSchedule"}, want: 1},
		"tainted on re-read":  {after: []string{"node.kubernetes.io/unschedulable=:NoSchedule"}, want: 1},
		"deregister fails ok": {before: []string{"x=:NoSchedule"}, err: errors.New("down"), want: 1},
	} {
		t.Run(name, func(t *testing.T) {
			taints := tc.before
			calls := 0
			p := pushers{wg: &sync.WaitGroup{}, deregister: func(ctx context.Context) (bool, error) {
				if _, ok := ctx.Deadline(); !ok {
					t.Error("deregister has no deadline")
				}
				calls++
				return tc.err == nil, tc.err
			}}
			refresh := func(context.Context) {
				if tc.after != nil {
					taints = tc.after
				}
			}
			p.leave(func() []string { return taints }, refresh, log)
			if calls != tc.want {
				t.Fatalf("deregister calls = %d, want %d", calls, tc.want)
			}
		})
	}
}

func TestLeaveWaitsForThePushers(t *testing.T) {
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	wg := &sync.WaitGroup{}
	release := make(chan struct{})
	done := false
	wg.Go(func() {
		<-release
		done = true
	})
	p := pushers{wg: wg, deregister: func(context.Context) (bool, error) {
		if !done {
			t.Error("deregistered while a registration was in flight")
		}
		return true, nil
	}}
	close(release)
	p.leave(func() []string { return []string{"t"} }, nil, log)
}

func TestLeaveWithoutRegistrarDoesNothing(t *testing.T) {
	pushers{}.leave(func() []string {
		t.Fatal("read the taints without a registrar")
		return nil
	}, nil, nil)
}

func TestLeaveGivesTheDeregistrationItsOwnTime(t *testing.T) {
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	p := pushers{wg: &sync.WaitGroup{}, deregister: func(ctx context.Context) (bool, error) {
		if ctx.Err() != nil {
			t.Error("deregister got an expired context after a slow node read")
		}
		return true, nil
	}}
	// The node read uses up all of its time.
	refresh := func(ctx context.Context) { <-ctx.Done() }
	p.leave(func() []string { return []string{"t"} }, refresh, log)
}
