package files

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func skillTar(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	for name, data := range files {
		mode := int64(0o600)
		if strings.HasSuffix(name, ".sh") {
			mode = 0o700
		}
		h := &tar.Header{Name: name, Typeflag: tar.TypeReg, Mode: mode, Size: int64(len(data))}
		if err := tw.WriteHeader(h); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write([]byte(data)); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func skillStore(t *testing.T) (*Store, string) {
	t.Helper()
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(dir, "skills")
	s, _ := newStore(t, Config{SkillsRoot: root})
	return s, root
}

func install(s *Store, name, version string, archive []byte) (SkillSummary, error) {
	return s.InstallSkill(context.Background(), SkillSpec{
		Name: name, Version: version, Size: int64(len(archive)), SHA256: sum(archive),
	}, bytes.NewReader(archive))
}

func TestInstallSkillPutsReadableFilesAndSkipsTheSameVersion(t *testing.T) {
	s, root := skillStore(t)
	archive := skillTar(t, map[string]string{"report/SKILL.md": "# v1", "report/scripts/run.sh": "echo"})

	got, err := install(s, "report", "v1", archive)
	if err != nil || !got.Installed || got.Files != 2 {
		t.Fatalf("install = %+v, %v", got, err)
	}
	modes := map[string]fs.FileMode{
		"report": 0o755, "report/scripts": 0o755, "report/SKILL.md": 0o644,
		"report/scripts/run.sh": 0o755, "report/.version": 0o644,
	}
	for rel, want := range modes {
		fi, err := os.Stat(filepath.Join(root, rel))
		if err != nil {
			t.Fatal(err)
		}
		if fi.Mode().Perm() != want {
			t.Errorf("%s mode %v, want %v", rel, fi.Mode().Perm(), want)
		}
	}
	if b, _ := os.ReadFile(filepath.Join(root, "report", SkillVersionFile)); string(b) != "v1" {
		t.Fatalf(".version = %q", b)
	}

	// The same version reads no data: a reader that fails proves it.
	again, err := s.InstallSkill(context.Background(), SkillSpec{
		Name: "report", Version: "v1", Size: int64(len(archive)), SHA256: sum(archive),
	}, failingReader{})
	if err != nil || again.Installed {
		t.Fatalf("second install = %+v, %v", again, err)
	}
}

type failingReader struct{}

func (failingReader) Read([]byte) (int, error) { return 0, errors.New("read") }

func TestInstallSkillReplacesTheWholeFolder(t *testing.T) {
	s, root := skillStore(t)
	if _, err := install(s, "report", "v1", skillTar(t, map[string]string{
		"report/SKILL.md": "# v1", "report/old.py": "old",
	})); err != nil {
		t.Fatal(err)
	}
	if _, err := install(s, "report", "v2", skillTar(t, map[string]string{"report/SKILL.md": "# v2"})); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(root, "report/SKILL.md")); string(b) != "# v2" {
		t.Fatalf("SKILL.md = %q", b)
	}
	if _, err := os.Stat(filepath.Join(root, "report/old.py")); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("a file of the old version stayed: %v", err)
	}
	ents, _ := os.ReadDir(root)
	if len(ents) != 1 {
		t.Fatalf("leftovers in the skills root: %v", ents)
	}
}

func TestABadSkillTarChangesNothing(t *testing.T) {
	s, root := skillStore(t)
	if _, err := install(s, "report", "v1", skillTar(t, map[string]string{"report/SKILL.md": "# v1"})); err != nil {
		t.Fatal(err)
	}
	for name, archive := range map[string][]byte{
		"other skill": skillTar(t, map[string]string{"other/SKILL.md": "x"}),
	} {
		if _, err := install(s, "report", "v2", archive); !errors.Is(err, ErrArchive) {
			t.Errorf("%s: err = %v, want ErrArchive", name, err)
		}
	}
	good := skillTar(t, map[string]string{"report/SKILL.md": "# v2"})
	if _, err := s.InstallSkill(context.Background(), SkillSpec{
		Name: "report", Version: "v2", Size: int64(len(good)), SHA256: strings.Repeat("0", 64),
	}, bytes.NewReader(good)); !errors.Is(err, ErrArchive) {
		t.Errorf("bad sha256: err = %v", err)
	}
	if b, _ := os.ReadFile(filepath.Join(root, "report/SKILL.md")); string(b) != "# v1" {
		t.Fatalf("a failed install changed the skill: %q", b)
	}
}

func TestInstallSkillRefusesBadNames(t *testing.T) {
	s, _ := skillStore(t)
	archive := skillTar(t, map[string]string{"x/SKILL.md": "x"})
	for _, name := range []string{"", ".hidden", "a/b", "..", strings.Repeat("a", 300)} {
		if _, err := install(s, name, "v1", archive); !errors.Is(err, ErrInvalid) {
			t.Errorf("name %q: err = %v, want ErrInvalid", name, err)
		}
	}
	if _, err := install(s, "x", "v\n1", archive); !errors.Is(err, ErrInvalid) {
		t.Errorf("version with a line break: err = %v", err)
	}
}

// The skills root must be the daemon's own folder: a link, or a folder of
// another user, would let that user change the skills or redirect writes.
func TestInstallSkillRefusesASkillsRootItDoesNotOwn(t *testing.T) {
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(dir, "elsewhere")
	if err := os.Mkdir(target, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "skills")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	roots := map[string]string{"link": link}
	if os.Geteuid() != 0 {
		roots["another user's folder"] = "/usr"
	}
	archive := skillTar(t, map[string]string{"report/SKILL.md": "x"})
	for name, root := range roots {
		s, _ := newStore(t, Config{SkillsRoot: root})
		if _, err := install(s, "report", "v1", archive); err == nil || errors.Is(err, os.ErrPermission) {
			t.Errorf("%s: err = %v, want the owner refusal", name, err)
		}
	}
	if ents, _ := os.ReadDir(target); len(ents) != 0 {
		t.Fatalf("the link target got files: %v", ents)
	}
}
