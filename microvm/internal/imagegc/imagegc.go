// Package imagegc removes node images that nothing used for a grace period:
// managed drive images that no VM has behind a slot, and templates that are
// not the current template and that no VM uses. The build-time GCs keep a
// few recent images; this sweep also removes those once they are unused.
package imagegc

import (
	"context"
	"log/slog"
	"slices"
	"time"
)

// Kind is one class of images.
type Kind struct {
	// Name labels logs and metrics ("managed", "template").
	Name string
	// List returns the image IDs on the node.
	List func() ([]string, error)
	// Keep returns the IDs that are in use now. A kept ID starts its grace
	// period again.
	Keep func() map[string]bool
	// Remove deletes one image unless it became used or pinned since Keep.
	// False: kept.
	Remove func(id string) (bool, error)
}

// Sweeper runs the passes. An image is removed after it was unused for
// Grace, counted from the last pass that saw it kept, or from the first
// pass that saw it (so an agent restart starts the grace again).
type Sweeper struct {
	Kinds    []Kind
	Grace    time.Duration
	Interval time.Duration
	Log      *slog.Logger
	// Removed, if set, gets each removal.
	Removed func(kind string)
	// Now is the clock. Default time.Now.
	Now func() time.Time

	lastUsed map[string]map[string]time.Time
}

func (s *Sweeper) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

// Pass runs one sweep over every kind and returns the removed IDs by kind.
func (s *Sweeper) Pass() map[string][]string {
	if s.lastUsed == nil {
		s.lastUsed = map[string]map[string]time.Time{}
	}
	out := map[string][]string{}
	for _, k := range s.Kinds {
		if removed := s.passKind(k); len(removed) > 0 {
			out[k.Name] = removed
		}
	}
	return out
}

func (s *Sweeper) passKind(k Kind) []string {
	ids, err := k.List()
	if err != nil {
		s.Log.Error("image GC: list", "kind", k.Name, "err", err)
		return nil
	}
	now := s.now()
	keep := k.Keep()
	last := s.lastUsed[k.Name]
	if last == nil {
		last = map[string]time.Time{}
		s.lastUsed[k.Name] = last
	}
	seen := map[string]bool{}
	var removed []string
	for _, id := range ids {
		seen[id] = true
		t, known := last[id]
		if keep[id] || !known {
			last[id] = now
			continue
		}
		if now.Sub(t) < s.Grace {
			continue
		}
		ok, err := k.Remove(id)
		if err != nil {
			s.Log.Error("image GC: remove", "kind", k.Name, "id", id, "err", err)
			continue
		}
		if !ok {
			last[id] = now
			continue
		}
		delete(last, id)
		removed = append(removed, id)
		if s.Removed != nil {
			s.Removed(k.Name)
		}
	}
	// Forget images that are gone, so the map does not grow.
	for id := range last {
		if !seen[id] {
			delete(last, id)
		}
	}
	if len(removed) > 0 {
		slices.Sort(removed)
		s.Log.Info("image GC removed unused images", "kind", k.Name, "removed", removed, "grace", s.Grace)
	}
	return removed
}

// Run runs a pass every Interval until ctx ends. The first pass runs after
// one Interval.
func (s *Sweeper) Run(ctx context.Context) {
	t := time.NewTicker(s.Interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			s.Pass()
		}
	}
}
