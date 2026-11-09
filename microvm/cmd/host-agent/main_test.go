package main

import (
	"math"
	"testing"
)

func TestCheckRanges(t *testing.T) {
	ok := flags{uidBase: 1000000, uidCount: 65536, maxScratchGiB: 100}
	if err := checkRanges(ok); err != nil {
		t.Fatal(err)
	}
	for name, f := range map[string]flags{
		"uid base wraps":     {uidBase: math.MaxUint32 + 6, uidCount: 10, maxScratchGiB: 1},
		"uid count wraps":    {uidBase: 1, uidCount: math.MaxUint32 + 2, maxScratchGiB: 1},
		"uid range too long": {uidBase: math.MaxUint32 - 5, uidCount: 10, maxScratchGiB: 1},
		"zero uid count":     {uidBase: 1000, maxScratchGiB: 1},
		"scratch wraps":      {uidBase: 1000, uidCount: 10, maxScratchGiB: math.MaxUint32 + 1},
	} {
		if err := checkRanges(f); err == nil {
			t.Errorf("%s: accepted %+v", name, f)
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
