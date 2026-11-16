//go:build darwin

package template

import (
	"os"
	"syscall"
)

func sysPrint(st os.FileInfo, p *fingerprint) {
	if s, ok := st.Sys().(*syscall.Stat_t); ok {
		p.dev, p.ino = uint64(s.Dev), s.Ino
		p.ctime = s.Ctimespec.Nano()
	}
}
