package relay

import (
	"errors"
	"io"
	"net"
	"sync"
	"testing"
	"time"
)

func TestEventsAndOpen(t *testing.T) {
	up := newUpstream(t)
	var mu sync.Mutex
	events := map[string]int{}
	r, sock, _ := newRelay(t, up, func(r *Relay) {
		r.MaxConns = 1
		r.Events = func(e string) {
			mu.Lock()
			defer mu.Unlock()
			events[e]++
		}
	})
	a := connect(t, sock)
	defer func() { _ = a.Close() }()
	if n := r.Open(); n != 1 {
		t.Fatalf("Open = %d, want 1", n)
	}
	over, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = over.Close() }()
	_ = over.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := over.Read(make([]byte, 1)); !errors.Is(err, io.EOF) {
		t.Fatalf("connection over the cap: %v", err)
	}
	mu.Lock()
	defer mu.Unlock()
	if events[EventAccepted] != 1 || events[EventOverCap] != 1 {
		t.Fatalf("events %v", events)
	}
}
