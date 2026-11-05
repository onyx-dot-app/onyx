package template

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"sync"
)

// FileSHA256 returns the SHA256 of one file.
func FileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() { _ = f.Close() }()
	h := sha256.New()
	if _, err := io.CopyBuffer(h, f, make([]byte, 1<<20)); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// HashFiles returns the SHA256 of each named file in dir. The files are
// hashed in parallel.
func HashFiles(dir string, names []string) (map[string]string, error) {
	out := make(map[string]string, len(names))
	var (
		mu       sync.Mutex
		wg       sync.WaitGroup
		firstErr error
	)
	for _, n := range names {
		wg.Go(func() {
			sum, err := FileSHA256(filepath.Join(dir, n))
			mu.Lock()
			defer mu.Unlock()
			if err != nil && firstErr == nil {
				firstErr = err
			}
			out[n] = sum
		})
	}
	wg.Wait()
	return out, firstErr
}
