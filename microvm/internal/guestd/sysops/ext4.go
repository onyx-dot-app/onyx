package sysops

import (
	"encoding/binary"
	"fmt"
)

// ext4UUID returns the UUID in an ext4 superblock (first 4 KiB of the
// device), or "" if there is no ext4 magic.
func ext4UUID(b []byte) string {
	const sb = 1024
	if len(b) < sb+0x78 || binary.LittleEndian.Uint16(b[sb+0x38:]) != 0xEF53 {
		return ""
	}
	u := b[sb+0x68 : sb+0x78]
	return fmt.Sprintf("%x-%x-%x-%x-%x", u[0:4], u[4:6], u[6:8], u[8:10], u[10:16])
}
