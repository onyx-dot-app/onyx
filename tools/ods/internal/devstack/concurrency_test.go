//go:build !windows

package devstack

import (
	"context"
	"testing"
	"time"
)

type barrierProvider struct {
	*fakeProvider
	entered chan<- struct{}
	release <-chan struct{}
}

func (p *barrierProvider) Prepare(ctx context.Context) error {
	if err := p.fakeProvider.Prepare(ctx); err != nil {
		return err
	}
	select {
	case p.entered <- struct{}{}:
	case <-ctx.Done():
		return ctx.Err()
	}
	select {
	case <-p.release:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func TestUpIndependentWorktreesPrepareConcurrently(t *testing.T) {
	registry := t.TempDir()
	stacks := []*Stack{newTestStack(t, registry), newTestStack(t, registry)}
	entered := make(chan struct{}, len(stacks))
	release := make(chan struct{})
	results := make(chan error, len(stacks))
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	opts := testOptions()
	opts.SkipPrepare = false
	opts.LockWait = 3 * time.Second
	for _, stack := range stacks {
		provider := &barrierProvider{
			fakeProvider: &fakeProvider{services: []string{"web"}},
			entered:      entered,
			release:      release,
		}
		go func() {
			_, err := stack.Up(ctx, provider, opts)
			results <- err
		}()
	}
	deadline := time.NewTimer(5 * time.Second)
	defer deadline.Stop()
	arrivals := 0
barrier:
	for arrivals < len(stacks) {
		select {
		case <-entered:
			arrivals++
		case <-deadline.C:
			t.Errorf("only %d of %d worktrees entered Prepare before release; independent startup is blocked", arrivals, len(stacks))
			cancel()
			break barrier
		}
	}
	close(release)
	for range stacks {
		if err := <-results; err != nil {
			t.Errorf("independent worktree startup: %v", err)
		}
	}
	if t.Failed() {
		return
	}
	first, err := stacks[0].Status()
	if err != nil {
		t.Fatal(err)
	}
	second, err := stacks[1].Status()
	if err != nil {
		t.Fatal(err)
	}
	if first == nil || second == nil || !first.Ready || !second.Ready {
		t.Fatalf("independent stacks did not become ready: %+v, %+v", first, second)
	}
	if first.Ports["web"] == second.Ports["web"] {
		t.Fatal("concurrent worktrees leased the same web port")
	}
}
