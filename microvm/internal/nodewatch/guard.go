package nodewatch

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"time"
)

// Annotation keys of ScaleDownGuard. The cluster autoscaler (GKE, AKS and
// the upstream cluster-autoscaler) does not remove a node with
// ScaleDownDisabledKey=true. GuardOwnerKey marks the value as the agent's,
// so the agent never removes a value that an operator set.
const (
	ScaleDownDisabledKey = "cluster-autoscaler.kubernetes.io/scale-down-disabled"
	GuardOwnerKey        = "onyx.app/craft-fc-scale-down-guard"
)

// errVMStarted stops a removal when a VM started during the check.
var errVMStarted = errors.New("a VM started")

// NodeAnnotator reads and annotates the agent's own Node.
type NodeAnnotator interface {
	Node(ctx context.Context) (Node, error)
	SetAnnotations(ctx context.Context, set map[string]*string) error
}

// ScaleDownGuard keeps the cluster autoscaler from removing the node while
// it runs VMs: VMs are not pods, so the autoscaler sees an empty node. It
// sets ScaleDownDisabledKey while VMs() > 0 (and reads the Node at each
// Once, to set it again if someone removed it), and removes it when the
// node has had no VMs for Grace. A failed read or patch is logged and
// tried again on the next Once. Once and Run are not safe for concurrent
// use; Kick is.
type ScaleDownGuard struct {
	Node     NodeAnnotator
	VMs      func() int
	Grace    time.Duration
	Interval time.Duration
	// Timeout bounds one Once. 0 means Interval.
	Timeout time.Duration
	Log     *slog.Logger
	// Now is time.Now when nil.
	Now func() time.Time

	applied   *bool
	idleSince time.Time
	failing   bool
	foreign   bool

	kickOnce sync.Once
	kickCh   chan struct{}
}

// Kick makes Run check at once, for example when a VM starts. It never
// blocks.
func (g *ScaleDownGuard) Kick() {
	select {
	case g.kicks() <- struct{}{}:
	default:
	}
}

func (g *ScaleDownGuard) kicks() chan struct{} {
	g.kickOnce.Do(func() { g.kickCh = make(chan struct{}, 1) })
	return g.kickCh
}

// Once checks the VM count and updates the annotation if needed.
func (g *ScaleDownGuard) Once(ctx context.Context) {
	block, decided := g.want()
	// An idle node with the annotation removed needs no read; a node with
	// VMs is read every time.
	if !decided || (!block && g.applied != nil && !*g.applied) {
		return
	}
	timeout := g.Timeout
	if timeout <= 0 {
		timeout = g.Interval
	}
	rctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	if err := g.apply(rctx, block); err != nil {
		if errors.Is(err, errVMStarted) {
			return
		}
		if !g.failing {
			if block {
				g.Log.Error("scale-down guard: node annotation failed; the cluster autoscaler can remove this node while VMs run", "err", err)
			} else {
				g.Log.Error("scale-down guard: annotation removal failed; the cluster autoscaler cannot remove this idle node", "err", err)
			}
		}
		g.failing = true
		return
	}
	g.failing = false
	g.applied = &block
}

// want returns whether scale-down must be blocked; decided is false while
// the node is idle for less than Grace (the annotation stays as it is).
func (g *ScaleDownGuard) want() (block, decided bool) {
	if g.VMs() > 0 {
		g.idleSince = time.Time{}
		return true, true
	}
	now := time.Now()
	if g.Now != nil {
		now = g.Now()
	}
	if g.idleSince.IsZero() {
		g.idleSince = now
	}
	return false, now.Sub(g.idleSince) >= g.Grace
}

func (g *ScaleDownGuard) apply(ctx context.Context, block bool) error {
	n, err := g.Node.Node(ctx)
	if err != nil {
		return err
	}
	ours := n.Annotations[GuardOwnerKey] == "true"
	current := n.Annotations[ScaleDownDisabledKey]
	switch {
	case block && current == "true":
		if !ours && !g.foreign {
			g.Log.Info("scale-down guard: the node already has the annotation from someone else; the agent leaves it", "annotation", ScaleDownDisabledKey)
		}
		g.foreign = !ours
		return nil
	case block:
		v := "true"
		if err := g.Node.SetAnnotations(ctx, map[string]*string{ScaleDownDisabledKey: &v, GuardOwnerKey: &v}); err != nil {
			return err
		}
		g.foreign = false
		g.Log.Info("scale-down guard: VMs run; the cluster autoscaler may not remove this node", "annotation", ScaleDownDisabledKey)
	case ours:
		// A VM can start during the Node read; Run checks again at once
		// (Kick) if one starts during the patch.
		if g.VMs() > 0 {
			g.idleSince = time.Time{}
			return errVMStarted
		}
		if err := g.Node.SetAnnotations(ctx, map[string]*string{ScaleDownDisabledKey: nil, GuardOwnerKey: nil}); err != nil {
			return err
		}
		g.Log.Info("scale-down guard: no VMs; the cluster autoscaler may remove this node", "idle_for", g.Grace)
	}
	return nil
}

// Run calls Once at once, then every Interval and at each Kick, until ctx
// ends.
func (g *ScaleDownGuard) Run(ctx context.Context) {
	t := time.NewTicker(g.Interval)
	defer t.Stop()
	for {
		g.Once(ctx)
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		case <-g.kicks():
		}
	}
}
