package cmd

import (
	"image"
	"image/color"
	"image/png"
	"io"
	"log"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/google/go-containerregistry/pkg/crane"
	"github.com/google/go-containerregistry/pkg/registry"
	"github.com/google/go-containerregistry/pkg/v1/random"
)

// shotFakeAWS puts an aws on PATH that appends its arguments, space-joined,
// as one line per call, and then runs script. It returns the call log path.
func shotFakeAWS(t *testing.T, script string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake aws is a shell script")
	}
	binDir := t.TempDir()
	callLog := filepath.Join(binDir, "calls")
	body := "#!/bin/sh\necho \"$*\" >> \"${0%/*}/calls\"\n" + script
	if err := os.WriteFile(filepath.Join(binDir, "aws"), []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir+string(os.PathListSeparator)+os.Getenv("PATH"))
	return callLog
}

// shotAWSCalls returns one entry per aws invocation.
func shotAWSCalls(t *testing.T, callLog string) []string {
	t.Helper()
	data, err := os.ReadFile(callLog)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

// shotWritePNG writes a solid w x h PNG, creating parent directories.
func shotWritePNG(t *testing.T, path string, w, h int, c color.Color) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := range h {
		for x := range w {
			img.Set(x, y, c)
		}
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	if err := png.Encode(f, img); err != nil {
		t.Fatal(err)
	}
}

// shotWriteFiles writes name -> content under root, creating directories.
func shotWriteFiles(t *testing.T, root string, files map[string]string) {
	t.Helper()
	for name, content := range files {
		full := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

// shotGitRepo creates a git repository with files staged, and makes it the
// working directory for the rest of the test.
func shotGitRepo(t *testing.T, files map[string]string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("uses a POSIX git setup")
	}
	t.Setenv("GIT_CONFIG_GLOBAL", os.DevNull)
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	root := t.TempDir()
	// Resolve symlinks so paths match what git rev-parse reports.
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	shotWriteFiles(t, root, files)
	for _, args := range [][]string{{"init", "-q"}, {"add", "."}} {
		cmd := exec.Command("git", args...)
		cmd.Dir = root
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	t.Chdir(root)
	return root
}

// shotFakeRegistry serves an in-memory registry with one random image per tag
// under <host>/app, and returns the host and the digest of each tag's query.
func shotFakeRegistry(t *testing.T, tags ...string) (string, map[string]string) {
	t.Helper()
	// Keep the Docker keychain away from the developer's real credentials.
	t.Setenv("DOCKER_CONFIG", t.TempDir())
	server := httptest.NewServer(registry.New(registry.Logger(log.New(io.Discard, "", 0))))
	t.Cleanup(server.Close)
	host := strings.TrimPrefix(server.URL, "http://")

	digests := map[string]string{}
	for _, tag := range tags {
		img, err := random.Image(64, 1)
		if err != nil {
			t.Fatal(err)
		}
		query := host + "/app:" + tag
		if err := crane.Push(img, query); err != nil {
			t.Fatalf("push %s: %v", query, err)
		}
		digest, err := img.Digest()
		if err != nil {
			t.Fatal(err)
		}
		digests[query] = digest.String()
	}
	return host, digests
}
