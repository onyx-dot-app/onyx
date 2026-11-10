//go:build !linux

package hostinfo

import "errors"

func diskFree(string) (uint64, error) { return 0, errors.New("disk stats need Linux") }
