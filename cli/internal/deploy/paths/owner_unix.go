//go:build !windows

package paths

import (
	"fmt"
	"os"
	"syscall"
)

// currentUID is a variable so tests can stand in for another user.
var currentUID = os.Getuid

// checkOwnedByUser fails unless dir is owned by the invoking user and neither
// its group nor other users can write to it. Group members cannot be listed
// reliably (NSS, LDAP), so any group write is refused.
func checkOwnedByUser(dir string) error {
	info, err := os.Stat(dir)
	if err != nil {
		return err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return fmt.Errorf("cannot read the owner of %s", dir)
	}
	if int(st.Uid) != currentUID() {
		return fmt.Errorf("%s is owned by another user", dir)
	}
	if info.Mode().Perm()&0o022 != 0 {
		return fmt.Errorf("%s is writable by its group or other users", dir)
	}
	return nil
}
