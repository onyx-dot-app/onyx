package execs

// ring keeps the last max bytes of one output stream, with absolute offsets.
type ring struct {
	buf   []byte
	start int64 // offset of buf[0]
	max   int
}

func (r *ring) append(p []byte) {
	r.buf = append(r.buf, p...)
	if over := len(r.buf) - r.max; over > 0 {
		r.buf = r.buf[over:]
		r.start += int64(over)
	}
}

func (r *ring) total() int64 { return r.start + int64(len(r.buf)) }

// size is the memory the ring holds.
func (r *ring) size() int { return cap(r.buf) }

// keep drops all but the last n bytes and frees the rest.
func (r *ring) keep(n int) {
	n = min(n, len(r.buf))
	if cap(r.buf) <= n {
		return
	}
	var nb []byte
	if n > 0 {
		nb = make([]byte, n)
		copy(nb, r.buf[len(r.buf)-n:])
	}
	r.start += int64(len(r.buf) - n)
	r.buf = nb
}

// read returns up to n bytes from off. If off is before the kept bytes,
// gapTo is the first kept offset and the data starts there.
func (r *ring) read(off int64, n int) (data []byte, gapTo int64, next int64) {
	if off < r.start {
		gapTo = r.start
		off = r.start
	}
	if off >= r.total() {
		return nil, gapTo, off
	}
	i := int(off - r.start)
	j := min(i+n, len(r.buf))
	data = make([]byte, j-i)
	copy(data, r.buf[i:j])
	return data, gapTo, off + int64(len(data))
}
