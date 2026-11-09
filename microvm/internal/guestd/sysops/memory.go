package sysops

import (
	"fmt"
	"os"
	"strconv"
)

// Guest memory knobs (ENG-4569). Variables, so tests can point them at
// plain files.
var (
	// PageReportingOrderPath is the smallest free block (2^order pages) that
	// the balloon's free page reporting returns to the host. The kernel sets
	// it when the virtio_balloon driver registers, so a boot parameter has
	// no effect; only a write after boot works.
	PageReportingOrderPath = "/sys/module/page_reporting/parameters/page_reporting_order"
	DropCachesPath         = "/proc/sys/vm/drop_caches"
	CompactMemoryPath      = "/proc/sys/vm/compact_memory"
)

// SetPageReportingOrder sets the page reporting order. Order 0 reports
// every free page; the kernel default (9, 2 MiB blocks) returns about half
// of the free memory of a guest after heavy work (results/mem.md).
func SetPageReportingOrder(order int) error {
	return writeKnob(PageReportingOrderPath, strconv.Itoa(order))
}

// PageReportingOrder reads the page reporting order.
func PageReportingOrder() (int, error) {
	raw, err := os.ReadFile(PageReportingOrderPath)
	if err != nil {
		return 0, err
	}
	return strconv.Atoi(string(trimNL(raw)))
}

// ReclaimMemory drops the clean page cache, dentries and inodes, then
// compacts memory. The freed pages go back to the host through free page
// reporting. Dirty pages stay; the call does not sync.
func ReclaimMemory() error {
	if err := writeKnob(DropCachesPath, "3"); err != nil {
		return err
	}
	return writeKnob(CompactMemoryPath, "1")
}

func writeKnob(path, v string) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_TRUNC, 0)
	if err != nil {
		return err
	}
	if _, err := f.WriteString(v); err != nil {
		_ = f.Close()
		return fmt.Errorf("write %s: %w", path, err)
	}
	return f.Close()
}

func trimNL(b []byte) []byte {
	for len(b) > 0 && (b[len(b)-1] == '\n' || b[len(b)-1] == ' ') {
		b = b[:len(b)-1]
	}
	return b
}
