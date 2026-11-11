package files

import (
	"archive/zip"
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
)

// ZipSpec is one zip call.
type ZipSpec struct {
	Path       string
	Exclude    []string
	SkipHidden bool
}

// ZipSummary describes a zip.
type ZipSummary struct {
	Files      int
	InputBytes int64
	ZipBytes   int64
	Skipped    int
}

type zipItem struct {
	rel, arc string
	size     int64
}

// Zip writes a deflate zip of the regular files under spec.Path to w. It
// checks the limits before it writes the first byte: the file sizes, and the
// files plus directories walked. Links, special files and directories deeper
// than maxDepth are left out.
func (s *Store) Zip(ctx context.Context, sessionID string, spec ZipSpec, w io.Writer) (ZipSummary, error) {
	var sum ZipSummary
	t, err := s.openRead(sessionID, spec.Path)
	if err != nil {
		return sum, err
	}
	defer func() { _ = t.root.Close() }()
	fi, err := t.root.Stat(t.rel)
	if err != nil {
		return sum, fsErr(err)
	}
	if !fi.IsDir() {
		return sum, fmt.Errorf("%w: %s is not a directory", ErrInvalid, spec.Path)
	}
	skip := setOf(spec.Exclude)
	var items []zipItem
	var total int64
	entries := 0
	count := func() error {
		if entries >= s.cfg.MaxZipEntries {
			return fmt.Errorf("%w: more than %d files and directories under %s", ErrLimit, s.cfg.MaxZipEntries, spec.Path)
		}
		entries++
		return nil
	}
	var walk func(rel, arc string, depth int) error
	walk = func(rel, arc string, depth int) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if depth > maxDepth {
			sum.Skipped++
			return nil
		}
		ents, err := readDir(t.root, rel, s.cfg.MaxZipEntries)
		if errors.Is(err, errDirTooBig) {
			return err
		}
		if err != nil {
			sum.Skipped++
			return nil
		}
		for _, e := range ents {
			name := e.Name()
			if skip[name] || (spec.SkipHidden && strings.HasPrefix(name, ".")) || strings.HasPrefix(name, writePrefix) {
				continue
			}
			child, carc := name, name
			if rel != "." {
				child = rel + "/" + name
			}
			if arc != "" {
				carc = arc + "/" + name
			}
			info, err := e.Info()
			if err != nil {
				sum.Skipped++
				continue
			}
			switch typeOf(info.Mode()) {
			case TypeDirectory:
				if err := count(); err != nil {
					return err
				}
				if err := walk(child, carc, depth+1); err != nil {
					return err
				}
			case TypeRegular:
				total += info.Size()
				if total > s.cfg.MaxZipBytes {
					return fmt.Errorf("%w: files under %s are over %d bytes", ErrLimit, spec.Path, s.cfg.MaxZipBytes)
				}
				if err := count(); err != nil {
					return err
				}
				items = append(items, zipItem{rel: child, arc: carc, size: info.Size()})
			default:
				sum.Skipped++
			}
		}
		return nil
	}
	if err := walk(t.rel, "", 0); err != nil {
		return sum, err
	}

	cw := &countWriter{w: w}
	zw := zip.NewWriter(cw)
	for _, it := range items {
		if err := ctx.Err(); err != nil {
			return sum, err
		}
		f, st, err := openRegular(t.root, it.rel, 0)
		if err != nil {
			sum.Skipped++
			continue
		}
		h := &zip.FileHeader{Name: it.arc, Method: zip.Deflate, Modified: st.ModTime()}
		h.SetMode(st.Mode().Perm())
		zf, err := zw.CreateHeader(h)
		if err != nil {
			_ = f.Close()
			return sum, err
		}
		// A file that grew since the walk is cut at the walk size.
		n, err := io.Copy(zf, io.LimitReader(f, it.size))
		_ = f.Close()
		if err != nil {
			return sum, err
		}
		sum.Files++
		sum.InputBytes += n
	}
	if err := zw.Close(); err != nil {
		return sum, err
	}
	sum.ZipBytes = cw.n
	return sum, nil
}

type countWriter struct {
	w io.Writer
	n int64
}

func (c *countWriter) Write(p []byte) (int, error) {
	n, err := c.w.Write(p)
	c.n += int64(n)
	return n, err
}
