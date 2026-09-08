// Package bunpkg reports whether a bun package's installed state is current.
// The devcontainer keeps node_modules in a persistent volume and bun never
// builds workspace libraries, so both routinely fall behind the sources in the
// workspace. Commands ask here before they run anything.
package bunpkg

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/charlievieth/fastwalk"
	log "github.com/sirupsen/logrus"
)

// lockStampName is the file inside node_modules recording the sha256 of the
// bun.lock that produced it. node_modules lives in a persistent volume in the
// devcontainer, so it routinely outlives lockfile updates in the workspace —
// the stamp is what lets us notice.
const lockStampName = ".ods-bun-lock-sha256"

// NodeModulesNeedsInstall reports whether bun install should be run for the
// package rooted at dir, along with a human-readable reason. Install is needed
// when node_modules is missing, empty, or was installed from a different
// bun.lock than the current one.
func NodeModulesNeedsInstall(dir string) (bool, string) {
	nodeModules := filepath.Join(dir, "node_modules")
	entries, err := os.ReadDir(nodeModules)
	if errors.Is(err, os.ErrNotExist) {
		return true, "node_modules not found"
	}
	if err != nil {
		// Couldn't read the directory for some other reason; let bun install
		// attempt to sort it out rather than silently skipping.
		return true, fmt.Sprintf("could not read node_modules (%v)", err)
	}
	if len(entries) == 0 {
		return true, "node_modules is empty"
	}

	lockHash, err := fileSHA256(filepath.Join(dir, "bun.lock"))
	if err != nil {
		// No lockfile to compare against; nothing more we can check.
		return false, ""
	}
	stamp, err := os.ReadFile(filepath.Join(nodeModules, lockStampName))
	if err != nil || strings.TrimSpace(string(stamp)) != lockHash {
		return true, "node_modules is stale (bun.lock changed since last install)"
	}
	return false, ""
}

// WriteLockStamp records the current bun.lock hash after a successful install.
// Best-effort: a failure only means the next run reinstalls, which is safe.
//
// The stamp is replaced via temp file + rename rather than written in place:
// the devcontainer's node_modules volume is shared across sessions that may
// run as different users (root agent sessions, the dev user), and an in-place
// write to a stamp owned by the other user fails — which would silently force
// a reinstall on every run. Rename needs only directory write permission and
// atomically replaces the previous owner's file.
func WriteLockStamp(dir string) {
	lockHash, err := fileSHA256(filepath.Join(dir, "bun.lock"))
	if err != nil {
		return
	}
	nodeModules := filepath.Join(dir, "node_modules")
	stampPath := filepath.Join(nodeModules, lockStampName)
	tmp, err := os.CreateTemp(nodeModules, lockStampName+".tmp-*")
	if err != nil {
		log.Debugf("Failed to create stamp temp file in %s: %v", nodeModules, err)
		return
	}
	_, writeErr := tmp.WriteString(lockHash + "\n")
	// World-readable so sessions running as other users can validate it.
	chmodErr := tmp.Chmod(0o644)
	closeErr := tmp.Close()
	if writeErr != nil || chmodErr != nil || closeErr != nil {
		_ = os.Remove(tmp.Name())
		log.Debugf("Failed to write stamp temp file %s: %v/%v/%v", tmp.Name(), writeErr, chmodErr, closeErr)
		return
	}
	if err := os.Rename(tmp.Name(), stampPath); err != nil {
		_ = os.Remove(tmp.Name())
		log.Debugf("Failed to replace %s: %v", stampPath, err)
	}
}

func fileSHA256(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}

// LibNeedsBuild reports whether a workspace library's dist/ is missing or
// stale relative to its sources, along with a human-readable reason. The
// staleness check compares newest mtimes, walking the package excluding its
// build output, dependencies, and hidden entries — cheap enough (a few
// thousand stats at most) to run before every script.
func LibNeedsBuild(pkgDir string) (bool, string) {
	if _, err := os.Stat(pkgDir); err != nil {
		// Not a checkout that has this package; nothing to do.
		return false, ""
	}
	distNewest, err := newestMtime(filepath.Join(pkgDir, "dist"), nil)
	if errors.Is(err, os.ErrNotExist) {
		return true, "has no dist build"
	}
	if err != nil {
		return true, fmt.Sprintf("dist is unreadable (%v)", err)
	}
	srcNewest, err := newestMtime(pkgDir, map[string]bool{"dist": true, "node_modules": true})
	if err != nil {
		return false, ""
	}
	if srcNewest.After(distNewest) {
		return true, "dist build is older than its sources"
	}
	return false, ""
}

// newestMtime returns the newest modification time under root, skipping
// directories named in excludeDirs and hidden entries.
func newestMtime(root string, excludeDirs map[string]bool) (time.Time, error) {
	var newest time.Time
	// fastwalk runs the callback on several goroutines, so guard the running max.
	var mu sync.Mutex
	err := fastwalk.Walk(nil, root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		name := d.Name()
		if path != root && (excludeDirs[name] || strings.HasPrefix(name, ".")) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		mu.Lock()
		if info.ModTime().After(newest) {
			newest = info.ModTime()
		}
		mu.Unlock()
		return nil
	})
	return newest, err
}
