//go:build !linux

package managed

// TmpfsStager is a plain directory on systems without tmpfs.
type TmpfsStager = DirStager

// Unmount does nothing on systems without tmpfs stages.
func Unmount(string) error { return nil }
