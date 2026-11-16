package jailer

import (
	"fmt"
	"sync"
)

// UIDPool hands out one jailer UID (used as UID and GID) per live VM.
type UIDPool struct {
	mu    sync.Mutex
	base  uint32
	count uint32
	used  map[uint32]bool
	next  uint32
}

// NewUIDPool returns a pool of count IDs that starts at base.
func NewUIDPool(base, count uint32) (*UIDPool, error) {
	if base == 0 || count == 0 {
		return nil, fmt.Errorf("uid base and count must be more than 0")
	}
	if uint64(base)+uint64(count) > 1<<32-1 {
		return nil, fmt.Errorf("uid range %d+%d overflows", base, count)
	}
	return &UIDPool{base: base, count: count, used: map[uint32]bool{}}, nil
}

// Get returns a free ID. It rotates through the range, so a freed ID is not
// used again at once.
func (p *UIDPool) Get() (uint32, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for i := uint32(0); i < p.count; i++ {
		off := (p.next + i) % p.count
		if !p.used[p.base+off] {
			p.used[p.base+off] = true
			p.next = (off + 1) % p.count
			return p.base + off, true
		}
	}
	return 0, false
}

// Reserve marks uid as used. It returns false if uid is out of range or
// already used.
func (p *UIDPool) Reserve(uid uint32) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	if uid < p.base || uid-p.base >= p.count || p.used[uid] {
		return false
	}
	p.used[uid] = true
	return true
}

// Put frees uid.
func (p *UIDPool) Put(uid uint32) {
	p.mu.Lock()
	defer p.mu.Unlock()
	delete(p.used, uid)
}

// InUse returns the number of IDs in use.
func (p *UIDPool) InUse() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.used)
}
