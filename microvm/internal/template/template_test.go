package template

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

func makeTemplate(t *testing.T, dir, version string, files []string) {
	t.Helper()
	d := filepath.Join(dir, version)
	if err := os.MkdirAll(d, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, f := range files {
		if err := os.WriteFile(filepath.Join(d, f), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := WriteManifest(d, Manifest{Version: version, VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, FirecrackerVersion: "v1.17.0"}); err != nil {
		t.Fatal(err)
	}
}

func TestStore(t *testing.T) {
	dir := t.TempDir()
	all := []string{RootfsFile, ScratchFile, VMStateFile, MemFile}
	makeTemplate(t, dir, "b-2", all)
	makeTemplate(t, dir, "a-1", all)
	makeTemplate(t, dir, "broken", []string{RootfsFile})
	s := &Store{Dir: dir}

	tpl, err := s.Get("a-1")
	if err != nil || tpl.VCPUs != 2 || tpl.Path(MemFile) != filepath.Join(dir, "a-1", MemFile) {
		t.Fatalf("get: %+v %v", tpl, err)
	}
	if _, err := s.Get("broken"); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_MISSING {
		t.Fatalf("broken: %v", err)
	}
	if _, err := s.Get("nope"); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_MISSING {
		t.Fatalf("missing: %v", err)
	}
	if _, err := s.Get("../a-1"); apierr.ReasonOf(err) != pb.ErrorReason_INVALID_ARGUMENT {
		t.Fatalf("traversal: %v", err)
	}
	list, err := s.List()
	if err != nil || len(list) != 2 || list[0].Version != "a-1" || list[1].Version != "b-2" {
		t.Fatalf("list: %v %v", list, err)
	}
}
