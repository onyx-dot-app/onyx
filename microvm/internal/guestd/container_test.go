package guestd

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"google.golang.org/grpc/metadata"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

func newContainerServer(t *testing.T, cfg Config, sys System) *Server {
	t.Helper()
	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	srv, err := NewServer(cfg, sys, m)
	if err != nil {
		t.Fatal(err)
	}
	return srv
}

// A key from the key file works at once; SetKey cannot replace it.
func TestKeyAtStart(t *testing.T) {
	srv := newContainerServer(t, Config{Key: testKey}, System{})
	ctx := context.Background()
	keyedIn := metadata.NewIncomingContext(ctx, metadata.Pairs(KeyHeader, testKey))
	if err := srv.check(keyedIn, pb.Sandboxd_Init_FullMethodName); err != nil {
		t.Fatalf("init with the key file key: %v", err)
	}
	wrong := metadata.NewIncomingContext(ctx, metadata.Pairs(KeyHeader, strings.Repeat("x", 32)))
	if err := srv.check(wrong, pb.Sandboxd_Init_FullMethodName); reason(err) != "UNAUTHENTICATED" {
		t.Fatalf("init with another key: %v", err)
	}
	if _, err := srv.SetKey(ctx, &pb.SetKeyRequest{Key: strings.Repeat("x", 32)}); reason(err) != "KEY_ALREADY_SET" {
		t.Fatalf("SetKey with another key: %v", err)
	}
	if r, err := srv.SetKey(ctx, &pb.SetKeyRequest{Key: testKey}); err != nil || !r.GetAlreadySet() {
		t.Fatalf("SetKey with the same key: %v %v", r, err)
	}
	if h, _ := srv.Health(ctx, &pb.HealthRequest{}); !h.GetKeySet() {
		t.Fatalf("health: key not set: %v", h)
	}
}

func TestKeyAtStartRejectsBadKey(t *testing.T) {
	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	for _, key := range []string{"short", strings.Repeat("k", 31) + " "} {
		if _, err := NewServer(Config{Key: key}, System{}, m); err == nil {
			t.Fatalf("key %q: no error", key)
		}
	}
}

// A state file that holds another key is an error, not a silent swap.
func TestKeyAtStartConflictsWithState(t *testing.T) {
	state := filepath.Join(t.TempDir(), "init.json")
	if err := os.WriteFile(state, []byte(`{"key":"`+strings.Repeat("x", 32)+`"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	if _, err := NewServer(Config{Key: testKey, StateFile: state}, System{}, m); err == nil {
		t.Fatal("no error for a state file with another key")
	}
	if _, err := NewServer(Config{Key: strings.Repeat("x", 32), StateFile: state}, System{}, m); err != nil {
		t.Fatalf("same key: %v", err)
	}
}

// A container daemon has no SetClock or AddEntropy: Init skips them.
func TestInitWithoutClockAndEntropy(t *testing.T) {
	f := &fakeSys{}
	sys := f.system()
	sys.SetClock, sys.AddEntropy = nil, nil
	srv := newContainerServer(t, Config{Key: testKey, GrowMounts: []string{"/mnt/scratch"}}, sys)
	resp, err := srv.Init(context.Background(), initReq())
	if err != nil {
		t.Fatal(err)
	}
	if resp.GetClockStep().AsDuration() != 0 || resp.GetEntropyCredited() {
		t.Fatalf("clock step %v, entropy credited %v", resp.GetClockStep().AsDuration(), resp.GetEntropyCredited())
	}
	if got := strings.Join(f.order, ","); got != "attach,grow,relay" {
		t.Fatalf("init steps %q", got)
	}
	if h, _ := srv.Health(context.Background(), &pb.HealthRequest{}); !h.GetInitialized() || h.GetGeneration() != 7 {
		t.Fatalf("health after init: %v", h)
	}
}
