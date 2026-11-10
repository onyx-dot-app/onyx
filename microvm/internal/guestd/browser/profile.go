package browser

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"syscall"
)

// profile is the browser's one profile. Chromium runs on the live copy
// (<work>/live). Stop saves it to saved after a clean exit, without the
// caches. Start makes a new live copy from saved, so a crash or a kill never
// changes the saved profile.
type profile struct {
	saved, work string
	cred        *syscall.Credential // owner of the copies; nil keeps the caller's
	max         int64
}

func (p *profile) live() string { return filepath.Join(p.work, "live") }

// skipDirs are Chromium cache and crash dirs, at any depth. Chromium
// rebuilds them. skipFiles are locks and per-run files.
var (
	skipDirs = map[string]bool{
		"Cache": true, "Code Cache": true, "GPUCache": true, "DawnCache": true, "DawnGraphiteCache": true,
		"DawnWebGPUCache": true, "GrShaderCache": true, "GraphiteDawnCache": true, "ShaderCache": true,
		"CacheStorage": true, "ScriptCache": true, "Crashpad": true, "component_crx_cache": true,
		"optimization_guide_model_store": true, "BrowserMetrics": true, "Safe Browsing": true,
	}
	skipFiles = map[string]bool{
		"SingletonLock": true, "SingletonSocket": true, "SingletonCookie": true,
		"DevToolsActivePort": true, "BrowserMetrics-spare.pma": true,
	}
)

// recoverSwap finishes a save that a daemon crash cut short. It removes
// .old only when the saved profile is in place.
func (p *profile) recoverSwap() error {
	old := p.saved + ".old"
	if _, err := os.Lstat(p.saved); errors.Is(err, fs.ErrNotExist) {
		if _, err := os.Lstat(old); err == nil {
			if err := os.Rename(old, p.saved); err != nil {
				return fmt.Errorf("restore saved profile: %w", err)
			}
		}
	} else if err != nil {
		return fmt.Errorf("saved profile: %w", err)
	}
	if err := os.RemoveAll(old); err != nil {
		return err
	}
	return os.RemoveAll(p.saved + ".tmp")
}

// resetLive makes the live profile a copy of the saved one (or empty).
func (p *profile) resetLive(ctx context.Context) error {
	if err := p.recoverSwap(); err != nil {
		return err
	}
	live := p.live()
	if err := os.MkdirAll(p.work, 0o755); err != nil {
		return err
	}
	if err := os.RemoveAll(live); err != nil {
		return err
	}
	if _, err := os.Stat(p.saved); errors.Is(err, fs.ErrNotExist) {
		if err := os.Mkdir(live, 0o700); err != nil {
			return err
		}
		return p.chown(live)
	}
	if _, err := copyTree(ctx, p.saved, live, false, p.cred, 0); err != nil {
		_ = os.RemoveAll(live)
		return fmt.Errorf("copy saved profile: %w", err)
	}
	return nil
}

// save copies the live profile, without caches, over the saved one. The
// swap is two renames; recoverSwap repairs a crash between them. If ctx
// ends during the copy, the saved profile stays as it was.
func (p *profile) save(ctx context.Context) (int64, error) {
	if err := p.recoverSwap(); err != nil {
		return 0, err
	}
	if err := os.MkdirAll(filepath.Dir(p.saved), 0o755); err != nil {
		return 0, err
	}
	tmp, old := p.saved+".tmp", p.saved+".old"
	n, err := copyTree(ctx, p.live(), tmp, true, p.cred, p.max)
	if err != nil {
		_ = os.RemoveAll(tmp)
		return 0, err
	}
	if err := syncDir(tmp); err != nil {
		_ = os.RemoveAll(tmp)
		return 0, err
	}
	if err := os.Rename(p.saved, old); err != nil && !errors.Is(err, fs.ErrNotExist) {
		_ = os.RemoveAll(tmp)
		return 0, err
	}
	if err := os.Rename(tmp, p.saved); err != nil {
		_ = os.Rename(old, p.saved)
		_ = os.RemoveAll(tmp)
		return 0, err
	}
	_ = syncDir(filepath.Dir(p.saved))
	_ = os.RemoveAll(old)
	return n, nil
}

func (p *profile) chown(path string) error {
	if p.cred == nil {
		return nil
	}
	return os.Lchown(path, int(p.cred.Uid), int(p.cred.Gid))
}

// errTooBig means a profile is over the size limit.
var errTooBig = errors.New("profile is over the size limit")

// copyTree copies the regular files and dirs of src to dst (new). It skips
// symlinks and special files, and with prune the cache dirs and lock files.
// Files are synced. max > 0 caps the total file bytes. It stops when ctx
// ends.
func copyTree(ctx context.Context, src, dst string, prune bool, cred *syscall.Credential, max int64) (int64, error) {
	var total int64
	p := &profile{cred: cred}
	err := filepath.WalkDir(src, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if prune && rel != "." {
			if d.IsDir() && skipDirs[d.Name()] {
				return filepath.SkipDir
			}
			if !d.IsDir() && skipFiles[d.Name()] {
				return nil
			}
		}
		switch {
		case d.IsDir():
			if err := os.Mkdir(target, 0o700); err != nil {
				return err
			}
			return p.chown(target)
		case d.Type().IsRegular():
			info, err := d.Info()
			if err != nil {
				return err
			}
			total += info.Size()
			if max > 0 && total > max {
				return fmt.Errorf("%w (%d bytes)", errTooBig, max)
			}
			if err := copyFile(path, target, info.Mode().Perm()); err != nil {
				return err
			}
			return p.chown(target)
		default:
			return nil
		}
	})
	return total, err
}

func copyFile(src, dst string, perm fs.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_EXCL, perm&0o700|0o600)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		_ = out.Close()
		return err
	}
	if err := out.Sync(); err != nil {
		_ = out.Close()
		return err
	}
	return out.Close()
}

func syncDir(dir string) error {
	f, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()
	return f.Sync()
}
