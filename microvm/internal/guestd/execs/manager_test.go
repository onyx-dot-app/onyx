package execs

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestNewManagerValidates(t *testing.T) {
	for name, cfg := range map[string]Config{
		"nil isolator":      {},
		"negative output":   {Isolator: ProcessGroups{}, OutputBytes: -1},
		"negative running":  {Isolator: ProcessGroups{}, MaxRunning: -1},
		"negative ended":    {Isolator: ProcessGroups{}, MaxEnded: -1},
		"negative ttl":      {Isolator: ProcessGroups{}, EndedTTL: -time.Second},
		"negative deadline": {Isolator: ProcessGroups{}, DefaultDeadline: -time.Second},
		"default above max": {Isolator: ProcessGroups{}, DefaultDeadline: 2 * time.Hour, MaxDeadline: time.Hour},
	} {
		if _, err := NewManager(cfg); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
}

// Ended records expire on the timer, also when no new command starts.
func TestEndedRecordsExpireWhenIdle(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}, EndedTTL: 50 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	e, err := m.Start(Spec{Argv: []string{"true"}, Env: []string{"PATH=/usr/bin:/bin"}})
	if err != nil {
		t.Fatal(err)
	}
	<-e.Done()
	deadline := time.Now().Add(5 * time.Second)
	for len(m.List(nil)) > 0 {
		if time.Now().After(deadline) {
			t.Fatal("ended record did not expire")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestLookPathRelativeToCommandDir(t *testing.T) {
	dir := t.TempDir()
	bin := filepath.Join(dir, "node_modules", ".bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	tool := filepath.Join(bin, "tool")
	if err := os.WriteFile(tool, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	got, err := lookPath("tool", dir, []string{"PATH=node_modules/.bin:/usr/bin"})
	if err != nil || got != tool {
		t.Fatalf("lookPath: %q %v", got, err)
	}
	if _, err := lookPath("tool", t.TempDir(), []string{"PATH=node_modules/.bin"}); err == nil {
		t.Fatal("found tool in another dir")
	}
}
