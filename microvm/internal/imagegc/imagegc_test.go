package imagegc

import (
	"errors"
	"io"
	"log/slog"
	"maps"
	"slices"
	"testing"
	"time"
)

type fakeImages struct {
	ids     map[string]bool
	keep    map[string]bool
	refuse  map[string]bool
	failRm  bool
	removed []string
}

func (f *fakeImages) kind(name string) Kind {
	return Kind{
		Name: name,
		List: func() ([]string, error) { return slices.Sorted(maps.Keys(f.ids)), nil },
		Keep: func() map[string]bool { return maps.Clone(f.keep) },
		Remove: func(id string) (bool, error) {
			if f.failRm {
				return false, errors.New("disk")
			}
			if f.refuse[id] {
				return false, nil
			}
			delete(f.ids, id)
			f.removed = append(f.removed, id)
			return true, nil
		},
	}
}

func set(ids ...string) map[string]bool {
	m := map[string]bool{}
	for _, id := range ids {
		m[id] = true
	}
	return m
}

func newSweeper(now *time.Time, kinds ...Kind) (*Sweeper, map[string]int) {
	counts := map[string]int{}
	return &Sweeper{
		Kinds: kinds, Grace: time.Hour, Interval: time.Minute,
		Log:     slog.New(slog.NewTextHandler(io.Discard, nil)),
		Removed: func(kind string) { counts[kind]++ },
		Now:     func() time.Time { return *now },
	}, counts
}

func TestUnusedImagesGoAfterTheGrace(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	f := &fakeImages{ids: set("old", "used", "current"), keep: set("used", "current")}
	s, counts := newSweeper(&now, f.kind("managed"))

	// The first pass only starts the grace, also for an old image.
	if got := s.Pass(); len(got) != 0 {
		t.Fatalf("first pass removed %v", got)
	}
	now = now.Add(59 * time.Minute)
	if got := s.Pass(); len(got) != 0 {
		t.Fatalf("pass within the grace removed %v", got)
	}
	now = now.Add(time.Minute)
	got := s.Pass()
	if !slices.Equal(got["managed"], []string{"old"}) || counts["managed"] != 1 {
		t.Fatalf("removed %v, counts %v", got, counts)
	}
	if !f.ids["used"] || !f.ids["current"] {
		t.Fatal("removed a used image")
	}
}

func TestAnImageThatWasUsedStartsItsGraceAgain(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	f := &fakeImages{ids: set("a"), keep: set("a")}
	s, _ := newSweeper(&now, f.kind("template"))
	s.Pass()
	now = now.Add(2 * time.Hour)
	s.Pass() // still used
	f.keep = set()
	now = now.Add(30 * time.Minute)
	if got := s.Pass(); len(got) != 0 {
		t.Fatalf("removed %v 30 min after its last use", got)
	}
	now = now.Add(31 * time.Minute)
	if got := s.Pass(); !slices.Equal(got["template"], []string{"a"}) {
		t.Fatalf("removed %v", got)
	}
}

func TestRefusedOrFailedRemovalsKeepTheImage(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	f := &fakeImages{ids: set("pinned", "x"), refuse: set("pinned"), failRm: true}
	s, counts := newSweeper(&now, f.kind("managed"))
	s.Pass()
	now = now.Add(2 * time.Hour)
	if got := s.Pass(); len(got) != 0 || counts["managed"] != 0 {
		t.Fatalf("removed %v with a failing disk", got)
	}
	f.failRm = false
	got := s.Pass()
	if !slices.Equal(got["managed"], []string{"x"}) || !f.ids["pinned"] {
		t.Fatalf("removed %v, left %v", got, f.ids)
	}
	// A refused image starts its grace again.
	now = now.Add(time.Minute)
	f.refuse = nil
	if got := s.Pass(); len(got) != 0 {
		t.Fatalf("removed %v right after a refusal", got)
	}
}

func TestGoneImagesAreForgotten(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	f := &fakeImages{ids: set("a", "b")}
	s, _ := newSweeper(&now, f.kind("managed"))
	s.Pass()
	delete(f.ids, "a")
	s.Pass()
	if _, ok := s.lastUsed["managed"]["a"]; ok || len(s.lastUsed["managed"]) != 1 {
		t.Fatalf("lastUsed = %v", s.lastUsed)
	}
}

func TestListErrorSkipsTheKind(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	bad := Kind{Name: "template", List: func() ([]string, error) { return nil, errors.New("io") },
		Keep: func() map[string]bool { t.Fatal("Keep after a list error"); return nil }}
	f := &fakeImages{ids: set("a")}
	s, _ := newSweeper(&now, bad, f.kind("managed"))
	s.Pass()
	now = now.Add(2 * time.Hour)
	if got := s.Pass(); !slices.Equal(got["managed"], []string{"a"}) {
		t.Fatalf("removed %v", got)
	}
}
