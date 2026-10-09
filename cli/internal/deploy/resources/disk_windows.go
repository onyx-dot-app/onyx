//go:build windows

package resources

import "golang.org/x/sys/windows"

// DiskAvailableGB returns the free space at path in GB (-1 = unknown).
func DiskAvailableGB(path string) int {
	p, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return -1
	}
	var freeBytesAvailable, totalBytes, totalFreeBytes uint64
	if err := windows.GetDiskFreeSpaceEx(p, &freeBytesAvailable, &totalBytes, &totalFreeBytes); err != nil {
		return -1
	}
	return int(freeBytesAvailable / (1 << 30))
}
