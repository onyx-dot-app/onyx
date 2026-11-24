package files

import (
	"archive/tar"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strings"
	"syscall"
)

// DefaultSkillsRoot is the folder of the installed skills. It is on the
// writable /var overlay; the image links /mnt/skills to it.
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
	lim, err := s.limits(spec.Limits)
	if err != nil {
		return sum, err
	}
	want := strings.ToLower(spec.SHA256)
	if !hexSHA256.MatchString(want) {
		return sum, fmt.Errorf("%w: sha256 must be 64 hex characters", ErrInvalid)
	}
	if spec.Size <= 0 || spec.Size > lim.StoredBytes {
		return sum, fmt.Errorf("%w: a tar of %d bytes is not in 1 to %d", ErrLimit, spec.Size, lim.StoredBytes)
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
	if _, err := io.Copy(io.Discard, br); err != nil {
		return sum, archiveErr(err)
	}
	if _, err := io.Copy(io.Discard, hr); err != nil {
		return sum, archiveErr(err)
	}
	if got := hex.EncodeToString(hr.h.Sum(nil)); hr.n != spec.Size || got != want {
		return sum, fmt.Errorf("%w: got %d bytes with sha256 %s, the header says %d bytes with %s",
			ErrArchive, hr.n, got, spec.Size, want)
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
