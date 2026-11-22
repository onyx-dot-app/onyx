package sysops

import (
	"os"
	"path/filepath"
	"testing"
)

func TestMemoryKnobs(t *testing.T) {
	dir := t.TempDir()
	knobs := map[*string]string{&PageReportingOrderPath: "9\n", &DropCachesPath: "0\n", &CompactMemoryPath: ""}
	for p, v := range knobs {
		old := *p
		*p = filepath.Join(dir, filepath.Base(old))
		t.Cleanup(func() { *p = old })
		if err := os.WriteFile(*p, []byte(v), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	if o, err := PageReportingOrder(); err != nil || o != 9 {
		t.Fatalf("order %d %v", o, err)
	}
	if err := SetPageReportingOrder(0); err != nil {
		t.Fatal(err)
	}
	if o, err := PageReportingOrder(); err != nil || o != 0 {
		t.Fatalf("order after set %d %v", o, err)
	}
	if err := ReclaimMemory(); err != nil {
		t.Fatal(err)
	}
	for p, want := range map[string]string{DropCachesPath: "3", CompactMemoryPath: "1"} {
		if got, _ := os.ReadFile(p); string(got) != want {
			t.Errorf("%s = %q, want %q", p, got, want)
		}
	}
	// A kernel without page reporting has no knob.
	PageReportingOrderPath = filepath.Join(dir, "missing")
	if err := SetPageReportingOrder(0); err == nil {
		t.Error("missing knob accepted")
	}
}
