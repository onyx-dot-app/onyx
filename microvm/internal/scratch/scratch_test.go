package scratch

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

func TestCheckSize(t *testing.T) {
	cases := []struct {
		req, tpl, max uint32
		want          pb.ErrorReason
	}{
		{1, 1, 10, pb.ErrorReason_ERROR_REASON_UNSPECIFIED},
		{10, 1, 10, pb.ErrorReason_ERROR_REASON_UNSPECIFIED},
		{0, 1, 10, pb.ErrorReason_SCRATCH_TOO_SMALL},
		{1, 2, 10, pb.ErrorReason_SCRATCH_TOO_SMALL},
		{11, 1, 10, pb.ErrorReason_SCRATCH_TOO_LARGE},
	}
	for _, c := range cases {
		err := CheckSize(c.req, c.tpl, c.max)
		got := pb.ErrorReason_ERROR_REASON_UNSPECIFIED
		if err != nil {
			got = apierr.ReasonOf(err)
		}
		if got != c.want {
			t.Errorf("CheckSize(%d, %d, %d) = %s, want %s", c.req, c.tpl, c.max, got, c.want)
		}
	}
}

func TestPrepare(t *testing.T) {
	dir := t.TempDir()
	if err := ProbeReflink(dir); errors.Is(err, ErrNoReflink) {
		t.Skipf("no reflink on %s: %v", dir, err)
	} else if err != nil {
		t.Fatal(err)
	}
	src := filepath.Join(dir, "src")
	if err := os.WriteFile(src, make([]byte, 8192), 0o644); err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(dir, "dst")
	if err := Prepare(src, dst, 2*GiB, os.Getuid(), os.Getgid()); err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(dst)
	if err != nil || st.Size() != 2*GiB || st.Mode().Perm() != 0o600 {
		t.Fatalf("dst: %v %v", st, err)
	}
	if err := Prepare(src, filepath.Join(dir, "small"), 4096, os.Getuid(), os.Getgid()); err == nil {
		t.Fatal("Prepare shrank the disk")
	}
	if _, err := os.Stat(filepath.Join(dir, "small")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("failed Prepare left a file: %v", err)
	}
	if err := Prepare(src, dst, 2*GiB, os.Getuid(), os.Getgid()); err == nil {
		t.Fatal("Prepare overwrote an existing disk")
	}
}
