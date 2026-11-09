//go:build !linux

package browser

import (
	"errors"
	"os"
	"path/filepath"
	"strconv"
)

func limitCgroup(string, int64) error { return errors.New("cgroups need Linux") }

func memoryCurrent(string) uint64 { return 0 }

func prepareX11(tmp string, display int) {
	d := strconv.Itoa(display)
	_ = os.Remove(filepath.Join(tmp, ".X"+d+"-lock"))
	_ = os.Remove(filepath.Join(tmp, ".X11-unix", "X"+d))
}
