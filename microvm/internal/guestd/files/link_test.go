//go:build linux

package files

import (
	"errors"
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestLinkMakesAndReplacesOnlyLinks(t *testing.T) {
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	onyx := filepath.Join(dir, "onyx")
	s, err := New(Config{SessionsRoot: filepath.Join(dir, "sessions"), OnyxRoot: onyx, Owner: &Owner{UID: os.Getuid(), GID: os.Getgid()}})
	if err != nil {
		t.Fatal(err)
	}
	link := dir + "/skills/pptx"
	readLink := func() string {
		t.Helper()
		got, err := os.Readlink(link)
		if err != nil {
			t.Fatal(err)
		}
		return got
	}

	if err := s.Link("", link, "/mnt/skills/pptx"); err != nil {
		t.Fatal(err)
	}
	if got := readLink(); got != "/mnt/skills/pptx" {
		t.Fatalf("link to %q", got)
	}
	if err := s.Link("", link, "/mnt/skills/other"); err != nil {
		t.Fatal(err)
	}
	if got := readLink(); got != "/mnt/skills/other" {
		t.Fatalf("replaced link to %q", got)
	}

	if err := s.Link("", onyx+"/a/b/link", "/mnt/skills/pptx"); err != nil {
		t.Fatal(err)
	}
	if got, err := os.Readlink(onyx + "/a/b/link"); err != nil || got != "/mnt/skills/pptx" {
		t.Fatalf("onyx link to %q, %v", got, err)
	}

	s.linkSwapped = func() { t.Fatal("Link swapped an entry that is not a link") }

	notes := dir + "/skills/notes"
	if err := os.WriteFile(notes, []byte("keep"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := s.Link("", notes, "/mnt/skills/notes"); !errors.Is(err, ErrExists) {
		t.Fatalf("link over a file: %v", err)
	}
	if b, err := os.ReadFile(notes); err != nil || string(b) != "keep" {
		t.Fatalf("file after a refused link: %q %v", b, err)
	}

	report := dir + "/skills/report"
	if err := os.Mkdir(report, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := s.Link("", report, "/mnt/skills/report"); !errors.Is(err, ErrExists) {
		t.Fatalf("link over a folder: %v", err)
	}
	if fi, err := os.Lstat(report); err != nil || !fi.IsDir() {
		t.Fatalf("folder after a refused link: %v %v", fi, err)
	}

	for name, call := range map[string]func() error{
		"session":      func() error { return s.Link(sid, "skills/x", "/mnt/skills/x") },
		"empty target": func() error { return s.Link("", dir+"/skills/x", "") },
		"denied path":  func() error { return s.Link("", "/proc/x", "/mnt/skills/x") },
	} {
		if err := call(); !errors.Is(err, ErrInvalid) {
			t.Fatalf("%s: %v", name, err)
		}
	}
	ents, err := os.ReadDir(dir + "/skills")
	if err != nil || len(ents) != 3 {
		t.Fatalf("skills folder holds %v %v, want notes, pptx and report only", ents, err)
	}
}

func TestLinkKeepsAnEntryThatACommandMovesInDuringTheSwap(t *testing.T) {
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := New(Config{SessionsRoot: filepath.Join(dir, "sessions")})
	if err != nil {
		t.Fatal(err)
	}
	skills := dir + "/skills"
	if err := os.MkdirAll(skills, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("/mnt/skills/old", skills+"/pptx"); err != nil {
		t.Fatal(err)
	}
	s.linkChecked = func() {
		if err := os.Remove(skills + "/pptx"); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(skills+"/pptx", []byte("first"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	s.linkSwapped = func() {
		if err := os.WriteFile(dir+"/second", []byte("second"), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.Rename(dir+"/second", skills+"/pptx"); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Link("", skills+"/pptx", "/mnt/skills/pptx"); !errors.Is(err, ErrExists) {
		t.Fatalf("link over a file: %v", err)
	}
	ents, err := os.ReadDir(skills)
	if err != nil {
		t.Fatal(err)
	}
	var kept []string
	for _, e := range ents {
		b, err := os.ReadFile(filepath.Join(skills, e.Name()))
		if err != nil {
			t.Fatal(err)
		}
		kept = append(kept, string(b))
	}
	slices.Sort(kept)
	if !slices.Equal(kept, []string{"first", "second"}) {
		t.Fatalf("files after the call: %v, want both kept", kept)
	}
}

func TestLinkPutsBackAnEntryWhenACommandDeletesTheNewLink(t *testing.T) {
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := New(Config{SessionsRoot: filepath.Join(dir, "sessions")})
	if err != nil {
		t.Fatal(err)
	}
	skills := dir + "/skills"
	if err := os.MkdirAll(skills, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("/mnt/skills/old", skills+"/pptx"); err != nil {
		t.Fatal(err)
	}
	s.linkChecked = func() {
		if err := os.Remove(skills + "/pptx"); err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(skills+"/pptx/scripts", 0o755); err != nil {
			t.Fatal(err)
		}
	}
	s.linkSwapped = func() {
		if err := os.Remove(skills + "/pptx"); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Link("", skills+"/pptx", "/mnt/skills/pptx"); !errors.Is(err, ErrExists) {
		t.Fatalf("link over a folder: %v", err)
	}
	ents, err := os.ReadDir(skills)
	if err != nil {
		t.Fatal(err)
	}
	if len(ents) != 1 || ents[0].Name() != "pptx" || !ents[0].IsDir() {
		t.Fatalf("entries after the call: %v, want only the folder pptx", ents)
	}
	if _, err := os.Stat(skills + "/pptx/scripts"); err != nil {
		t.Fatalf("folder contents: %v", err)
	}
}
