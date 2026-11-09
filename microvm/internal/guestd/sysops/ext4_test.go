package sysops

import (
	"encoding/binary"
	"testing"
)

func TestExt4UUID(t *testing.T) {
	b := make([]byte, 4096)
	if got := ext4UUID(b); got != "" {
		t.Fatalf("no magic: %q", got)
	}
	binary.LittleEndian.PutUint16(b[1024+0x38:], 0xEF53)
	for i := range 16 {
		b[1024+0x68+i] = byte(i * 17)
	}
	if got := ext4UUID(b); got != "00112233-4455-6677-8899-aabbccddeeff" {
		t.Fatalf("uuid %q", got)
	}
	if got := ext4UUID(b[:1100]); got != "" {
		t.Fatalf("short buffer: %q", got)
	}
}
