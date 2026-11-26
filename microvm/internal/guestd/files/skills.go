package files

import (
	"archive/tar"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strings"
	"syscall"
)

// DefaultSkillsRoot is the folder of the installed skills, shared by every
// session of the VM. It is on the writable /var overlay, and root owns it and
// its parents.
const DefaultSkillsRoot = "/var/lib/onyx/skills"

// SkillVersionFile holds the version of an installed skill, in its folder.
const SkillVersionFile = ".version"

const maxSkillVersionBytes = 256

// SkillSpec is the header of an InstallSkill.
type SkillSpec struct {
	Name    string
	Version string
	// Size and SHA256 (hex) of the tar.
	Size   int64
	SHA256 string
	Limits Limits
}

// SkillSummary describes an InstallSkill.
type SkillSummary struct {
	// Installed is false when the folder already had the version.
	Installed     bool
	Files         int64
	ExpandedBytes int64
}

func checkSkillSpec(spec SkillSpec) error {
	n := spec.Name
	if !restorableName(n) || strings.ContainsRune(n, '/') || strings.HasPrefix(n, ".") {
		return fmt.Errorf("%w: bad skill name %q", ErrInvalid, n)
	}
	v := spec.Version
	if v == "" || len(v) > maxSkillVersionBytes || strings.ContainsAny(v, "\r\n\x00") {
		return fmt.Errorf("%w: the version must be 1 to %d bytes with no line breaks", ErrInvalid, maxSkillVersionBytes)
	}
	return nil
}

// InstallSkill puts the skill files of a tar stream at SkillsRoot/<name>.
// If the folder already has spec.Version, it reads nothing from r.
func (s *Store) InstallSkill(ctx context.Context, spec SkillSpec, r io.Reader) (SkillSummary, error) {
	var sum SkillSummary
	if err := checkSkillSpec(spec); err != nil {
		return sum, err
	}
	want, lim, err := s.checkArchive(spec.SHA256, spec.Size, spec.Limits)
	if err != nil {
		return sum, err
	}
	// One install at a time: removeLeftovers below would delete the staging
	// directory of another install.
	unlock, err := s.lock(ctx, "\x00skills")
	if err != nil {
		return sum, err
	}
	defer unlock()
	if err := os.MkdirAll(s.cfg.SkillsRoot, 0o755); err != nil {
		return sum, fsErr(err)
	}
	// A link, or a folder of another user, would let that user change the
	// skills or send the daemon's writes elsewhere.
	if fi, err := os.Lstat(s.cfg.SkillsRoot); err != nil || !fi.IsDir() || !ownedByUs(fi) {
		return sum, errors.Join(fmt.Errorf("the skills root %s is not a folder of uid %d", s.cfg.SkillsRoot, os.Geteuid()), err)
	}
	root, err := os.OpenRoot(s.cfg.SkillsRoot)
	if err != nil {
		return sum, fsErr(err)
	}
	defer func() { _ = root.Close() }()
	if err := removeLeftovers(root); err != nil {
		return sum, fmt.Errorf("recover an interrupted install: %w", err)
	}
	if installedVersion(root, spec.Name) == spec.Version {
		return sum, nil
	}

	staging := randName(stagingPrefix)
	if err := root.Mkdir(staging, 0o700); err != nil {
		return sum, err
	}
	defer func() { _ = root.RemoveAll(staging) }()
	st, err := root.OpenRoot(staging)
	if err != nil {
		return sum, err
	}
	defer func() { _ = st.Close() }()

	hr := &hashReader{r: &ctxReader{ctx: ctx, r: r}, h: sha256.New(), max: spec.Size}
	br := &budgetReader{r: hr}
	var rs RestoreSummary
	x := &extractor{root: st, lim: lim, allowed: map[string]bool{spec.Name: true}, sum: &rs, present: map[string]bool{},
		made: map[string]bool{}, buf: make([]byte, 1<<20), budget: br, own: func(string) error { return nil }}
	if err := x.run(ctx, tar.NewReader(br)); err != nil {
		return sum, err
	}
	if err := verifyArchive(br, hr, spec.Size, want); err != nil {
		return sum, err
	}
	if !x.present[spec.Name] {
		return sum, fmt.Errorf("%w: the tar has nothing under %s/", ErrArchive, spec.Name)
	}
	if err := st.WriteFile(spec.Name+"/"+SkillVersionFile, []byte(spec.Version), 0o644); err != nil {
		return sum, err
	}
	if err := readableModes(st, spec.Name); err != nil {
		return sum, err
	}
	if err := swapRoots(root, staging, []string{spec.Name}, x.present); err != nil {
		return sum, err
	}
	return SkillSummary{Installed: true, Files: rs.Files, ExpandedBytes: rs.ExpandedBytes}, nil
}

func ownedByUs(fi fs.FileInfo) bool {
	st, ok := fi.Sys().(*syscall.Stat_t)
	return ok && int(st.Uid) == os.Geteuid()
}

// installedVersion returns the version of the installed skill, or "".
func installedVersion(root *os.Root, name string) string {
	f, err := root.OpenFile(name+"/"+SkillVersionFile, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return ""
	}
	defer func() { _ = f.Close() }()
	b, err := io.ReadAll(io.LimitReader(f, maxSkillVersionBytes+1))
	if err != nil || len(b) > maxSkillVersionBytes {
		return ""
	}
	return string(b)
}

// readableModes makes every directory 0755 and every file 0644, or 0755
// when the tar gave it an execute bit, so the sandbox user can read and
// run the skill but not change it.
func readableModes(root *os.Root, top string) error {
	return fs.WalkDir(root.FS(), top, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		mode := fs.FileMode(0o755)
		if !d.IsDir() {
			fi, err := d.Info()
			if err != nil {
				return err
			}
			if fi.Mode()&0o111 == 0 {
				mode = 0o644
			}
		}
		if err := root.Chmod(p, mode); err != nil {
			return errors.Join(fmt.Errorf("chmod %s", p), err)
		}
		return nil
	})
}
