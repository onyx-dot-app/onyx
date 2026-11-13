package loopstore

import (
	"os"
	"path/filepath"
	"testing"
)

const gib = uint64(1) << 30

func TestAutoSize(t *testing.T) {
	for _, tc := range []struct {
		free, want uint64
		fail       bool
	}{
		{free: 100 * gib, want: 80 * gib},
		{free: 25 * gib, want: 20 * gib},
		{free: 24 * gib, fail: true},
		{free: 10000 * gib, want: MaxBytes},
		{free: 100*gib + 12345, want: 80 * gib},
	} {
		got, err := AutoSize(tc.free)
		if tc.fail != (err != nil) || got != tc.want {
			t.Errorf("AutoSize(%d GiB) = %d, %v; want %d, fail %v", tc.free>>30, got, err, tc.want, tc.fail)
		}
		if err == nil && got%(1<<20) != 0 {
			t.Errorf("AutoSize(%d) = %d is not MiB-aligned", tc.free, got)
		}
	}
}

func TestImageSize(t *testing.T) {
	if got, err := imageSize(50, 100*gib); err != nil || got != 50*gib {
		t.Errorf("explicit size: %d %v", got, err)
	}
	if _, err := imageSize(10, 100*gib); err == nil {
		t.Error("a size below the floor was accepted")
	}
	if _, err := imageSize(200, 100*gib); err == nil {
		t.Error("a size above the free space was accepted")
	}
	if got, err := imageSize(0, 100*gib); err != nil || got != 80*gib {
		t.Errorf("auto size: %d %v", got, err)
	}
}

func TestParseMode(t *testing.T) {
	for _, s := range []string{"auto", "off"} {
		if m, err := ParseMode(s); err != nil || string(m) != s {
			t.Errorf("ParseMode(%q) = %q, %v", s, m, err)
		}
	}
	if _, err := ParseMode("on"); err == nil {
		t.Error(`ParseMode("on") was accepted`)
	}
}

func TestParseDevNumber(t *testing.T) {
	if ma, mi, err := parseDevNumber("7:12\n"); err != nil || ma != 7 || mi != 12 {
		t.Errorf("parseDevNumber = %d:%d %v", ma, mi, err)
	}
	for _, s := range []string{"", "7", "7:x", "a:1"} {
		if _, _, err := parseDevNumber(s); err == nil {
			t.Errorf("parseDevNumber(%q) was accepted", s)
		}
	}
}

func TestRootfsRel(t *testing.T) {
	for _, tc := range []struct{ data, rootfs, want string }{
		{"/var/lib/craft-fc", "/var/lib/craft-fc/rootfs", "rootfs"},
		{"/var/lib/craft-fc/", "/var/lib/craft-fc/a/b", "a/b"},
		{"/var/lib/craft-fc", "/opt/rootfs", ""},
		{"/var/lib/craft-fc", "/var/lib/craft-fc", ""},
		{"/var/lib/craft-fc", "/var/lib/craft-fc-other/rootfs", ""},
		{"/var/lib/craft-fc", "", ""},
	} {
		if got := rootfsRel(tc.data, tc.rootfs); got != tc.want {
			t.Errorf("rootfsRel(%q, %q) = %q, want %q", tc.data, tc.rootfs, got, tc.want)
		}
	}
}

func putDrive(t *testing.T, dir, manifest, image string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, rootfsManifest), []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, rootfsImage), []byte(image), 0o644); err != nil {
		t.Fatal(err)
	}
}

func readDrive(t *testing.T, dir string) (string, string) {
	t.Helper()
	m, err := os.ReadFile(filepath.Join(dir, rootfsManifest))
	if err != nil {
		t.Fatal(err)
	}
	i, err := os.ReadFile(filepath.Join(dir, rootfsImage))
	if err != nil {
		t.Fatal(err)
	}
	return string(m), string(i)
}

// The init container writes the root drive before the agent mounts the store
// over the data dir: the agent copies a new build in and keeps a current one.
func TestSyncRootfs(t *testing.T) {
	lower, upper := t.TempDir(), t.TempDir()
	if copied, err := syncRootfs(lower, upper, "rootfs"); err != nil || copied {
		t.Fatalf("no lower drive: copied %v, %v", copied, err)
	}

	putDrive(t, filepath.Join(lower, "rootfs"), "m1", "image one")
	if copied, err := syncRootfs(lower, upper, "rootfs"); err != nil || !copied {
		t.Fatalf("first copy: copied %v, %v", copied, err)
	}
	if m, i := readDrive(t, filepath.Join(upper, "rootfs")); m != "m1" || i != "image one" {
		t.Fatalf("upper drive %q %q", m, i)
	}
	if _, err := os.Stat(filepath.Join(lower, "rootfs", rootfsImage)); err != nil {
		t.Fatalf("the lower drive must stay for the init container: %v", err)
	}
	if copied, err := syncRootfs(lower, upper, "rootfs"); err != nil || copied {
		t.Fatalf("same build: copied %v, %v", copied, err)
	}

	putDrive(t, filepath.Join(lower, "rootfs"), "m2", "image two")
	if copied, err := syncRootfs(lower, upper, "rootfs"); err != nil || !copied {
		t.Fatalf("new build: copied %v, %v", copied, err)
	}
	if m, i := readDrive(t, filepath.Join(upper, "rootfs")); m != "m2" || i != "image two" {
		t.Fatalf("upper drive after a new build %q %q", m, i)
	}
	for _, leftover := range []string{"rootfs.new", "rootfs.old"} {
		if _, err := os.Stat(filepath.Join(upper, leftover)); !os.IsNotExist(err) {
			t.Errorf("%s left: %v", leftover, err)
		}
	}

	// A manifest without an image is an unfinished install: no copy.
	if err := os.Remove(filepath.Join(lower, "rootfs", rootfsImage)); err != nil {
		t.Fatal(err)
	}
	putDrive(t, filepath.Join(lower, "other"), "m3", "x")
	if err := os.Remove(filepath.Join(lower, "other", rootfsImage)); err != nil {
		t.Fatal(err)
	}
	if copied, err := syncRootfs(lower, upper, "other"); err != nil || copied {
		t.Fatalf("lower drive without image: copied %v, %v", copied, err)
	}
}
