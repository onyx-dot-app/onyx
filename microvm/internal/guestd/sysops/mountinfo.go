package sysops

import (
	"fmt"
	"strings"
)

// mountedOn reports whether a mountinfo line has device major:minor mounted
// on mountPoint.
func mountedOn(mountinfo, mountPoint string, major, minor uint32) bool {
	want := fmt.Sprintf("%d:%d", major, minor)
	for _, line := range strings.Split(mountinfo, "\n") {
		// id parent major:minor root mountpoint options ...
		f := strings.Fields(line)
		if len(f) >= 5 && f[2] == want && f[4] == mountPoint {
			return true
		}
	}
	return false
}
