package main

import (
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/imagegc"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
)

func TestTemplateGCKeepsTheCurrentAndUsedTemplates(t *testing.T) {
	store := &template.Store{Dir: t.TempDir()}
	for _, v := range []string{"old", "used", "current"} {
		if _, err := template.WriteFake(store.Dir, v, template.Key{
			ImageRef: "onyxdotapp/sandbox:v5.1.0", FirecrackerVersion: "v1.17.0", CPUModel: "cpu", HostKernel: "6.18.56",
			GuestKernelSHA256: strings.Repeat("1", 64), CAFingerprint: strings.Repeat("c", 64), VCPUs: 2, MemMiB: 4096, ScratchGiB: 1,
		}); err != nil {
			t.Fatal(err)
		}
	}
	var current atomic.Pointer[string]
	now := time.Unix(1_800_000_000, 0)
	s := &imagegc.Sweeper{
		Kinds: []imagegc.Kind{templateKind(store, func() map[string]bool { return map[string]bool{"used": true} }, &current)},
		Grace: time.Hour, Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
		Now: func() time.Time { return now },
	}

	// No build named the current template yet: nothing is swept.
	s.Pass()
	now = now.Add(2 * time.Hour)
	if got := s.Pass(); len(got) != 0 {
		t.Fatalf("removed %v before a build", got)
	}

	c := "current"
	current.Store(&c)
	s.Pass()
	now = now.Add(2 * time.Hour)
	if got := s.Pass(); !slices.Equal(got["template"], []string{"old"}) {
		t.Fatalf("removed %v", got)
	}
	for _, v := range []string{"used", "current"} {
		if _, err := os.Stat(filepath.Join(store.Dir, v)); err != nil {
			t.Fatalf("%s: %v", v, err)
		}
	}
}
