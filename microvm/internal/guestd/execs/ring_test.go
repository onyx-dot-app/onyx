package execs

import "testing"

func TestRing(t *testing.T) {
	r := ring{max: 4}
	r.append([]byte("ab"))
	r.append([]byte("cdef"))
	if r.start != 2 || string(r.buf) != "cdef" || r.total() != 6 {
		t.Fatalf("ring %d %q", r.start, r.buf)
	}
	data, gapTo, next := r.read(0, 10)
	if string(data) != "cdef" || gapTo != 2 || next != 6 {
		t.Fatalf("read(0) = %q %d %d", data, gapTo, next)
	}
	data, gapTo, next = r.read(3, 2)
	if string(data) != "de" || gapTo != 0 || next != 5 {
		t.Fatalf("read(3) = %q %d %d", data, gapTo, next)
	}
	if data, _, next = r.read(6, 2); len(data) != 0 || next != 6 {
		t.Fatalf("read(6) = %q %d", data, next)
	}
}
