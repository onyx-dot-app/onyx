package browser

import (
	"fmt"
	"net"

	"golang.org/x/sys/unix"
)

// checkPeerUID fails unless the peer of the unix conn c runs as uid.
func checkPeerUID(c net.Conn, uid uint32) error {
	uc, ok := c.(*net.UnixConn)
	if !ok {
		return fmt.Errorf("browser service conn is %T, not a unix conn", c)
	}
	raw, err := uc.SyscallConn()
	if err != nil {
		return err
	}
	var cred *unix.Ucred
	var credErr error
	if err := raw.Control(func(fd uintptr) {
		cred, credErr = unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
	}); err != nil {
		return err
	}
	if credErr != nil {
		return fmt.Errorf("browser service peer: %w", credErr)
	}
	if cred.Uid != uid {
		return fmt.Errorf("browser service socket listener runs as uid %d, not %d", cred.Uid, uid)
	}
	return nil
}
