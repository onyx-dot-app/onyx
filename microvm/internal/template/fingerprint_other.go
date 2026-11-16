//go:build !linux && !darwin

package template

import "os"

func sysPrint(os.FileInfo, *fingerprint) {}
