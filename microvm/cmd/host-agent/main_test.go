package main

import (
	"context"
	"math"
	"testing"
	"time"
)

func TestCheckRanges(t *testing.T) {
	ok := flags{uidBase: 1000000, uidCount: 65536, maxScratchGiB: 100, tplVCPUs: 2, tplMemMiB: 4096, tplScratchGiB: 1, tplKeep: 2,
		managedKeep: 3, managedZipMiB: 256, managedMaxMiB: 512, managedFiles: 50000, managedBuilds: 1, swapTimeout: time.Second, memOverhead: 128}
	if err := checkRanges(ok); err != nil {
		t.Fatal(err)
	}
	for name, f := range map[string]flags{
		"uid base wraps":     {uidBase: math.MaxUint32 + 6, uidCount: 10, maxScratchGiB: 1},
		"uid count wraps":    {uidBase: 1, uidCount: math.MaxUint32 + 2, maxScratchGiB: 1},
		"uid range too long": {uidBase: math.MaxUint32 - 5, uidCount: 10, maxScratchGiB: 1},
		"zero uid count":     {uidBase: 1000, maxScratchGiB: 1},
		"scratch wraps":      {uidBase: 1000, uidCount: 10, maxScratchGiB: math.MaxUint32 + 1},
		"template keep 0":    {uidBase: 1000, uidCount: 10, maxScratchGiB: 10, tplVCPUs: 2, tplMemMiB: 4096, tplScratchGiB: 1},
		"template scratch":   {uidBase: 1000, uidCount: 10, maxScratchGiB: 10, tplVCPUs: 2, tplMemMiB: 4096, tplScratchGiB: 11, tplKeep: 2},
	} {
		if err := checkRanges(f); err == nil {
			t.Errorf("%s: accepted %+v", name, f)
		}
	}
	for name, edit := range map[string]func(f *flags){
		"managed keep 0":      func(f *flags) { f.managedKeep = 0 },
		"managed zip 0":       func(f *flags) { f.managedZipMiB = 0 },
		"managed content 0":   func(f *flags) { f.managedMaxMiB = 0 },
		"managed files 0":     func(f *flags) { f.managedFiles = 0 },
		"managed builds 0":    func(f *flags) { f.managedBuilds = 0 },
		"managed swap time 0": func(f *flags) { f.swapTimeout = 0 },
		"vm overhead 0":       func(f *flags) { f.memOverhead = 0 },
		"vm overhead huge":    func(f *flags) { f.memOverhead = 1 << 20 },
	} {
		f := ok
		edit(&f)
		if err := checkRanges(f); err == nil {
			t.Errorf("%s: accepted %+v", name, f)
		}
	}
}

func TestStartDrainWatchChecks(t *testing.T) {
	if err := startDrainWatch(context.Background(), flags{}, nil, nil); err != nil {
		t.Fatalf("off: %v", err)
	}
	for name, f := range map[string]flags{
		"no taint keys": {watchDrain: true, drainPoll: time.Second, nodeID: "n"},
		"poll too fast": {watchDrain: true, drainTaints: "a", drainPoll: time.Millisecond, nodeID: "n"},
		"no node name":  {watchDrain: true, drainTaints: "a", drainPoll: time.Second},
		"not in a pod":  {watchDrain: true, drainTaints: "a", drainPoll: time.Second, nodeID: "n"},
	} {
		t.Setenv("KUBERNETES_SERVICE_HOST", "")
		if err := startDrainWatch(context.Background(), f, nil, nil); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestParsePortsRejectsAnEmptyList(t *testing.T) {
	for _, in := range []string{"", ",", " , "} {
		if ports, err := parsePorts(in); err == nil {
			t.Errorf("%q: got %v, want an error", in, ports)
		}
	}
	if ports, err := parsePorts("52, 3010"); err != nil || len(ports) != 2 || ports[0] != 52 || ports[1] != 3010 {
		t.Fatalf("parse: %v %v", ports, err)
	}
}

func TestCheckListen(t *testing.T) {
	tls := flags{listen: ":7443", tlsCert: "c", tlsKey: "k", clientCA: "ca", dialMax: 64}
	for name, f := range map[string]flags{
		"unix only": {dialMax: 64},
		"mtls":      tls,
	} {
		if err := checkListen(f); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
	noCA := tls
	noCA.clientCA = ""
	noListen := tls
	noListen.listen = ""
	sansOnly := flags{clientSANs: "spiffe://x", dialMax: 64}
	noDials := tls
	noDials.dialMax = 0
	for name, f := range map[string]flags{
		"listen without CA":   noCA,
		"TLS without listen":  noListen,
		"SANs without listen": sansOnly,
		"zero dial cap":       noDials,
	} {
		if err := checkListen(f); err == nil {
			t.Errorf("%s: accepted %+v", name, f)
		}
	}
}
