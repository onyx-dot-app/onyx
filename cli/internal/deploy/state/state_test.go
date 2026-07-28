package state

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestLoadMissingReturnsNilNil(t *testing.T) {
	m, err := Load(t.TempDir())
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if m != nil {
		t.Fatalf("expected nil manifest, got %+v", m)
	}
}

func TestSaveLoadRoundTrip(t *testing.T) {
	root := t.TempDir()
	in := &Manifest{
		InstalledTag: "v4.4.6",
		CLIVersion:   "v1.2.3",
		Mode:         ModeLite,
		IncludeCraft: true,
		InstalledAt:  time.Now().UTC().Truncate(time.Second),
	}
	if err := in.RecordFile(root, "deployment/docker-compose.yml", []byte("name: onyx\n")); err != nil {
		t.Fatalf("RecordFile: %v", err)
	}
	if err := in.Save(root); err != nil {
		t.Fatalf("Save: %v", err)
	}

	out, err := Load(root)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if out.SchemaVersion != SchemaVersion {
		t.Errorf("schema version not stamped: %d", out.SchemaVersion)
	}
	if out.InstalledTag != in.InstalledTag || out.Mode != in.Mode || !out.IncludeCraft {
		t.Errorf("round trip mismatch: %+v", out)
	}
	entry, ok := out.Files["deployment/docker-compose.yml"]
	if !ok || entry.SHA256 != HashBytes([]byte("name: onyx\n")) {
		t.Errorf("file entry not preserved: %+v", out.Files)
	}
}

func TestLoadCorruptFails(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(Path(root), []byte("{not json"), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}
	if _, err := Load(root); err == nil {
		t.Fatal("expected error for corrupt manifest")
	}
}

func TestLoadNewerSchemaFails(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(Path(root), []byte(`{"schema_version": 999}`), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}
	_, err := Load(root)
	if err == nil || !strings.Contains(err.Error(), "newer onyx-cli") {
		t.Fatalf("expected newer-schema error, got %v", err)
	}
}

func TestSaveIsAtomic(t *testing.T) {
	root := t.TempDir()
	first := &Manifest{InstalledTag: "v1.0.0"}
	if err := first.Save(root); err != nil {
		t.Fatalf("Save: %v", err)
	}
	second := &Manifest{InstalledTag: "v2.0.0"}
	if err := second.Save(root); err != nil {
		t.Fatalf("Save: %v", err)
	}
	// No temp files left behind, and the content is the latest write.
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatalf("ReadDir: %v", err)
	}
	for _, e := range entries {
		if strings.Contains(e.Name(), ".tmp-") {
			t.Errorf("leftover temp file %s", e.Name())
		}
	}
	got, err := Load(root)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.InstalledTag != "v2.0.0" {
		t.Errorf("got tag %s", got.InstalledTag)
	}
}

func TestPristineRoundTripAndForget(t *testing.T) {
	root := t.TempDir()
	m := &Manifest{}
	content := []byte("services: {}\n")
	if err := m.RecordFile(root, "deployment/docker-compose.onyx-lite.yml", content); err != nil {
		t.Fatalf("RecordFile: %v", err)
	}

	got, err := Pristine(root, "deployment/docker-compose.onyx-lite.yml")
	if err != nil {
		t.Fatalf("Pristine: %v", err)
	}
	if string(got) != string(content) {
		t.Errorf("pristine content mismatch: %q", got)
	}

	if err := m.ForgetFile(root, "deployment/docker-compose.onyx-lite.yml"); err != nil {
		t.Fatalf("ForgetFile: %v", err)
	}
	if _, ok := m.Files["deployment/docker-compose.onyx-lite.yml"]; ok {
		t.Error("entry still in manifest after ForgetFile")
	}
	got, err = Pristine(root, "deployment/docker-compose.onyx-lite.yml")
	if err != nil {
		t.Fatalf("Pristine after forget: %v", err)
	}
	if got != nil {
		t.Errorf("pristine copy still present after ForgetFile")
	}
}

func TestUserEdited(t *testing.T) {
	root := t.TempDir()
	m := &Manifest{}
	destRel := "deployment/docker-compose.yml"
	content := []byte("name: onyx\n")

	if err := os.MkdirAll(filepath.Join(root, "deployment"), 0755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	onDisk := filepath.Join(root, filepath.FromSlash(destRel))
	if err := os.WriteFile(onDisk, content, 0644); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := m.RecordFile(root, destRel, content); err != nil {
		t.Fatalf("RecordFile: %v", err)
	}

	edited, err := m.UserEdited(root, destRel)
	if err != nil {
		t.Fatalf("UserEdited: %v", err)
	}
	if edited {
		t.Error("unmodified file reported as edited")
	}

	if err := os.WriteFile(onDisk, []byte("name: onyx\n# hand edit\n"), 0644); err != nil {
		t.Fatalf("edit: %v", err)
	}
	edited, err = m.UserEdited(root, destRel)
	if err != nil {
		t.Fatalf("UserEdited: %v", err)
	}
	if !edited {
		t.Error("edited file not detected")
	}

	// No baseline recorded -> treated as edited.
	edited, err = m.UserEdited(root, "deployment/env.template")
	if err != nil {
		t.Fatalf("UserEdited: %v", err)
	}
	if !edited {
		t.Error("file without baseline should report edited")
	}

	// Recorded but deleted on disk -> nothing to preserve.
	if err := os.Remove(onDisk); err != nil {
		t.Fatalf("remove: %v", err)
	}
	edited, err = m.UserEdited(root, destRel)
	if err != nil {
		t.Fatalf("UserEdited: %v", err)
	}
	if edited {
		t.Error("missing file should not report edited")
	}
}
