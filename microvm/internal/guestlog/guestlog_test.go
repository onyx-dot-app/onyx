package guestlog

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const (
	id1 = "11111111-1111-4111-8111-111111111111"
	id2 = "22222222-2222-4222-8222-222222222222"
)

type fixture struct {
	t     *testing.T
	lay   jailer.Layout
	out   bytes.Buffer
	mu    sync.Mutex
	vms   []agent.VM
	clock time.Time
	count map[string][2]int
	s     *Shipper
}

func newFixture(t *testing.T, s *Shipper, ids ...string) *fixture {
	f := &fixture{t: t, lay: jailer.Layout{ChrootBase: t.TempDir()}, clock: time.Unix(1000, 0), count: map[string][2]int{}}
	for i, id := range ids {
		f.vms = append(f.vms, agent.VM{SandboxID: id, Generation: uint64(i + 1), TenantID: "tenant-" + id[:1], State: pb.VMState_VM_STATE_RUNNING})
		if err := os.MkdirAll(f.lay.RootDir(id), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	s.Layout = f.lay
	s.VMs = func() []agent.VM {
		f.mu.Lock()
		defer f.mu.Unlock()
		return append([]agent.VM(nil), f.vms...)
	}
	s.Out = slog.New(slog.NewJSONHandler(&f.out, nil))
	s.now = func() time.Time { return f.clock }
	s.Count = func(stream string, shipped, dropped int) {
		c := f.count[stream]
		f.count[stream] = [2]int{c[0] + shipped, c[1] + dropped}
	}
	f.s = s
	return f
}

func (f *fixture) write(id, stream, data string) {
	f.t.Helper()
	path := f.lay.ConsoleLog(id)
	if stream == Firecracker {
		path = f.lay.HostPath(id, jailer.LogFile)
	}
	fh, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		f.t.Fatal(err)
	}
	defer func() { _ = fh.Close() }()
	if _, err := fh.WriteString(data); err != nil {
		f.t.Fatal(err)
	}
}

// lines returns the shipped records and clears the output.
func (f *fixture) lines() []map[string]any {
	f.t.Helper()
	var out []map[string]any
	for _, l := range strings.Split(strings.TrimSpace(f.out.String()), "\n") {
		if l == "" {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(l), &m); err != nil {
			f.t.Fatalf("not JSON: %q", l)
		}
		out = append(out, m)
	}
	f.out.Reset()
	return out
}

func texts(recs []map[string]any) []string {
	var out []string
	for _, r := range recs {
		if l, ok := r["line"].(string); ok {
			out = append(out, l)
		}
	}
	return out
}

func eq(t *testing.T, got []string, want ...string) {
	t.Helper()
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestShipsLinesWithVMFields(t *testing.T) {
	f := newFixture(t, &Shipper{}, id1)
	f.s.Start(t.Context())
	f.write(id1, Console, "boot ok\r\n\nsecond\npart")
	f.write(id1, Firecracker, "fc warning\n")
	f.s.Tick()
	recs := f.lines()
	eq(t, texts(recs), "boot ok", "second", "fc warning")
	r := recs[0]
	if r["kind"] != "guest_log" || r["stream"] != Console || r["sandbox_id"] != id1 || r["tenant_id"] != "tenant-1" || r["generation"] != float64(1) {
		t.Fatalf("record fields: %v", r)
	}
	if recs[2]["stream"] != Firecracker {
		t.Fatalf("firecracker stream: %v", recs[2])
	}
	f.write(id1, Console, "ial\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "partial")
	if c := f.count[Console]; c[0] != len("boot ok\r\n\nsecond\npartial\n") || c[1] != 0 {
		t.Fatalf("console count %v", c)
	}
}

func TestRateLimitDropsAndResumes(t *testing.T) {
	f := newFixture(t, &Shipper{VMRate: 100, VMBurst: 100}, id1)
	f.s.Start(t.Context())
	f.write(id1, Console, strings.Repeat("123456789\n", 100))
	f.s.Tick()
	recs := f.lines()
	if got := len(texts(recs)); got != 10 {
		t.Fatalf("shipped %d lines over a 100-byte budget", got)
	}
	last := recs[len(recs)-1]
	if last["msg"] != "guest log rate limit" || last["dropped_bytes"] != float64(900) {
		t.Fatalf("no drop notice: %v", last)
	}
	if c := f.count[Console]; c != [2]int{100, 900} {
		t.Fatalf("count %v", c)
	}
	// The budget refills; the next line after the skip is whole.
	f.clock = f.clock.Add(time.Second)
	f.write(id1, Console, "next\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "next")
}

func TestRateLimitSkipMidLine(t *testing.T) {
	f := newFixture(t, &Shipper{VMRate: 20, VMBurst: 20}, id1)
	f.s.Start(t.Context())
	f.write(id1, Console, "short\n"+strings.Repeat("x", 50))
	f.s.Tick()
	eq(t, texts(f.lines()), "short")
	f.clock = f.clock.Add(10 * time.Second)
	// The rest of the skipped line is not shipped as a line of its own.
	f.write(id1, Console, "tail-of-x\nok\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "ok")
}

func TestNodeBudgetIsShared(t *testing.T) {
	f := newFixture(t, &Shipper{VMRate: 1000, VMBurst: 1000, NodeRate: 25}, id1, id2)
	f.s.Start(t.Context())
	// Node burst is 4 s = 100 bytes, for both VMs together.
	f.write(id1, Console, strings.Repeat("123456789\n", 10))
	f.write(id2, Console, strings.Repeat("123456789\n", 10))
	f.s.Tick()
	if got := len(texts(f.lines())); got != 10 {
		t.Fatalf("shipped %d lines over a 100-byte node budget", got)
	}
	if c := f.count[Console]; c != [2]int{100, 100} {
		t.Fatalf("count %v", c)
	}
}

func TestLongLinesAreTruncated(t *testing.T) {
	f := newFixture(t, &Shipper{MaxLine: 8}, id1)
	f.s.Start(t.Context())
	f.write(id1, Console, "0123456789abc\nok\n0123456789")
	f.s.Tick()
	recs := f.lines()
	eq(t, texts(recs), "01234567", "ok", "01234567")
	if recs[0]["truncated"] != true || recs[1]["truncated"] != nil {
		t.Fatalf("truncated flags: %v", recs)
	}
	f.write(id1, Console, "rest\nnext\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "next")
}

func TestAdoptedVMStartsAtEnd(t *testing.T) {
	f := newFixture(t, &Shipper{}, id1)
	f.write(id1, Console, "before the restart\nhalf")
	f.s.Start(t.Context())
	f.write(id1, Console, " line\nafter\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "after")
	// A VM created after Start is read from its start.
	f.mu.Lock()
	f.vms = append(f.vms, agent.VM{SandboxID: id2, Generation: 9, State: pb.VMState_VM_STATE_RUNNING})
	f.mu.Unlock()
	if err := os.MkdirAll(f.lay.RootDir(id2), 0o755); err != nil {
		t.Fatal(err)
	}
	f.write(id2, Console, "first\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "first")
}

func TestReleaseFlushesAndForgets(t *testing.T) {
	f := newFixture(t, &Shipper{}, id1)
	f.s.Start(t.Context())
	f.write(id1, Console, "line\nno newline")
	// Another generation is not this tail.
	f.s.Release(agent.VM{SandboxID: id1, Generation: 99})
	if len(f.lines()) != 0 {
		t.Fatal("release of another generation shipped lines")
	}
	f.s.Release(f.vms[0])
	eq(t, texts(f.lines()), "line", "no newline")
	if err := os.RemoveAll(filepath.Dir(f.lay.RootDir(id1))); err != nil {
		t.Fatal(err)
	}
	f.mu.Lock()
	f.vms = nil
	f.mu.Unlock()
	f.s.Tick()
	if len(f.s.tail) != 0 {
		t.Fatal("tail kept after release")
	}
}

func TestExitedAndGoneVMsAreDropped(t *testing.T) {
	f := newFixture(t, &Shipper{}, id1)
	f.s.Start(t.Context())
	f.mu.Lock()
	f.vms[0].State = pb.VMState_VM_STATE_EXITED
	f.mu.Unlock()
	f.write(id1, Console, "late\n")
	f.s.Tick()
	if len(f.lines()) != 0 || len(f.s.tail) != 0 {
		t.Fatal("an exited VM is still tailed")
	}
}
