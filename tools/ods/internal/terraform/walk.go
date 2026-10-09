package terraform

import (
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/charlievieth/fastwalk"
)

// skipDirs are never worth descending into for .tf files. `.terraform` holds
// provider plugins and vendored modules, which are not ours to format or lint.
var skipDirs = map[string]struct{}{
	".git":         {},
	".terraform":   {},
	".venv":        {},
	"node_modules": {},
	"venv":         {},
}

// Discover returns the .tf files to check.
//
// Explicit paths win: pre-commit passes the staged filenames, so a normal
// commit never walks the tree at all. A directory argument, or no argument, is
// walked concurrently with fastwalk.
func Discover(roots []string) ([]string, error) {
	if len(roots) == 0 {
		return nil, nil
	}

	var files []string
	seen := make(map[string]struct{})
	// fastwalk calls the callback from several goroutines, so the collector
	// needs a lock of its own.
	var mu sync.Mutex
	add := func(p string) {
		mu.Lock()
		defer mu.Unlock()
		if _, dup := seen[p]; dup {
			return
		}
		seen[p] = struct{}{}
		files = append(files, p)
	}

	for _, root := range roots {
		info, err := os.Stat(root)
		if err != nil {
			return nil, err
		}
		if !info.IsDir() {
			if isTerraformFile(root) {
				add(root)
			}
			continue
		}
		if err := walkDir(root, add); err != nil {
			return nil, err
		}
	}

	sort.Strings(files)
	return files, nil
}

func walkDir(root string, add func(string)) error {
	// fastwalk fans out across the tree and reuses the dirent type from
	// readdir, so it avoids a stat syscall per entry.
	conf := fastwalk.Config{Follow: false}
	return fastwalk.Walk(&conf, root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if _, skip := skipDirs[d.Name()]; skip {
				return filepath.SkipDir
			}
			return nil
		}
		if isTerraformFile(path) {
			add(path)
		}
		return nil
	})
}

func isTerraformFile(path string) bool {
	if !strings.HasSuffix(path, ".tf") {
		return false
	}
	// An explicit path can still point inside a vendored provider directory.
	for _, part := range strings.Split(filepath.ToSlash(path), "/") {
		if _, skip := skipDirs[part]; skip {
			return false
		}
	}
	return true
}
