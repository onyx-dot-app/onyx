package basedigest

import (
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/google/go-containerregistry/pkg/crane"
	"github.com/google/go-containerregistry/pkg/registry"
	"github.com/google/go-containerregistry/pkg/v1/random"
	"github.com/google/go-containerregistry/pkg/v1/remote/transport"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// fakeRegistry serves an in-memory registry holding one random image per tag
// and counts the manifest requests it answers. It returns the registry host,
// the digest pushed for each tag, and the request counter.
func fakeRegistry(t *testing.T, tags ...string) (string, map[string]string, func(path string) int) {
	t.Helper()
	// Keep the Docker keychain away from the developer's real credentials.
	t.Setenv("DOCKER_CONFIG", t.TempDir())

	var mu sync.Mutex
	requests := map[string]int{}
	handler := registry.New(registry.Logger(log.New(io.Discard, "", 0)))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/manifests/") && r.Method != http.MethodPut {
			mu.Lock()
			requests[r.URL.Path]++
			mu.Unlock()
		}
		handler.ServeHTTP(w, r)
	}))
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

	// Count only what the code under test asks for, not the pushes above.
	mu.Lock()
	clear(requests)
	mu.Unlock()

	count := func(path string) int {
		mu.Lock()
		defer mu.Unlock()
		return requests[path]
	}
	return host, digests, count
}

func TestResolve_returnsTheDigestTheTagPointsAt(t *testing.T) {
	host, digests, _ := fakeRegistry(t, "1")

	got, err := Resolve(host + "/app:1")
	if err != nil {
		t.Fatalf("Resolve failed: %v", err)
	}

	if want := digests[host+"/app:1"]; got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

// An unknown manifest never resolves, so it must fail on the first attempt
// instead of backing off.
func TestResolve_failsAnUnknownTagWithoutRetrying(t *testing.T) {
	host, _, count := fakeRegistry(t, "1")

	_, err := Resolve(host + "/app:missing")

	if err == nil || !strings.HasPrefix(err.Error(), "could not resolve "+host+"/app:missing: ") {
		t.Fatalf("expected a resolution error naming the query, got %v", err)
	}
	var terr *transport.Error
	if !errors.As(err, &terr) || terr.StatusCode != http.StatusNotFound {
		t.Fatalf("expected a wrapped 404 transport error, got %v", err)
	}
	// One HEAD and its GET fallback make up a single attempt.
	if got := count("/v2/app/manifests/missing"); got != 2 {
		t.Fatalf("expected 2 manifest requests from one attempt, got %d", got)
	}
}

func TestRetryable(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want bool
	}{
		{"rate limit", &transport.Error{StatusCode: http.StatusTooManyRequests}, true},
		{"server error", &transport.Error{StatusCode: http.StatusBadGateway}, true},
		{"unknown manifest", &transport.Error{StatusCode: http.StatusNotFound}, false},
		{"rejected credential", &transport.Error{StatusCode: http.StatusUnauthorized}, false},
		{"connection reset", errors.New("read: connection reset by peer"), true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := retryable(tt.err); got != tt.want {
				t.Fatalf("expected %v, got %v", tt.want, got)
			}
		})
	}
}

func TestResolveAll_asksOncePerDistinctTag(t *testing.T) {
	host, digests, count := fakeRegistry(t, "1", "2")
	refs := []Ref{
		{Path: "a/Dockerfile", Name: host + "/app", Tag: "1"},
		{Path: "b/Dockerfile", Name: host + "/app", Tag: "1"},
		{Path: "b/Dockerfile", Name: host + "/app", Tag: "2"},
	}

	resolved, err := ResolveAll(refs)
	if err != nil {
		t.Fatalf("ResolveAll failed: %v", err)
	}

	if len(resolved) != 2 || resolved[host+"/app:1"] != digests[host+"/app:1"] || resolved[host+"/app:2"] != digests[host+"/app:2"] {
		t.Fatalf("expected %v, got %v", digests, resolved)
	}
	if got := count("/v2/app/manifests/1"); got != 1 {
		t.Fatalf("expected tag 1 to be resolved once, got %d requests", got)
	}
}

func TestResolveAll_reportsEveryFailure(t *testing.T) {
	host, _, _ := fakeRegistry(t, "1")
	refs := []Ref{
		{Name: host + "/app", Tag: "gone-b"},
		{Name: host + "/app", Tag: "1"},
		{Name: host + "/app", Tag: "gone-a"},
	}

	resolved, err := ResolveAll(refs)

	if resolved != nil {
		t.Fatalf("expected no partial result, got %v", resolved)
	}
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	lines := strings.Split(err.Error(), "\n")
	if len(lines) != 2 ||
		!strings.HasPrefix(lines[0], "could not resolve "+host+"/app:gone-a: ") ||
		!strings.HasPrefix(lines[1], "could not resolve "+host+"/app:gone-b: ") {
		t.Fatalf("expected one sorted line per failed tag, got %q", err.Error())
	}
}

// gitRepo creates a git repository holding the given files, all staged.
func gitRepo(t *testing.T, files ...string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("uses a POSIX git setup")
	}
	gittest.IsolateConfig(t)
	root := t.TempDir()
	for _, name := range files {
		full := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for _, args := range [][]string{{"init", "-q"}, {"add", "."}} {
		cmd := exec.Command("git", args...)
		cmd.Dir = root
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	return root
}

func TestTrackedFiles_keepsDockerfilesAndCIYAML(t *testing.T) {
	root := gitRepo(t,
		"backend/Dockerfile",
		"web/Dockerfile.dev",
		".github/workflows/build.yml",
		".github/actions/dhi-base-images/action.yaml",
		".github/workflows/README.md",
		"deployment/helm/values.yaml",
		"README.md",
	)
	// An untracked Dockerfile is not part of the repository.
	if err := os.WriteFile(filepath.Join(root, "Dockerfile"), nil, 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := TrackedFiles(root)
	if err != nil {
		t.Fatalf("TrackedFiles failed: %v", err)
	}

	want := []string{
		".github/actions/dhi-base-images/action.yaml",
		".github/workflows/build.yml",
		"backend/Dockerfile",
		"web/Dockerfile.dev",
	}
	if !slices.Equal(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestTrackedFiles_reportsAFailedListing(t *testing.T) {
	root := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(root))

	if _, err := TrackedFiles(root); err == nil || !strings.HasPrefix(err.Error(), "git ls-files: ") {
		t.Fatalf("expected a git ls-files error, got %v", err)
	}
}

func TestFindRefs_reportsAnUnreadableFile(t *testing.T) {
	_, err := FindRefs(t.TempDir(), []string{"missing/Dockerfile"})

	if err == nil || !strings.HasPrefix(err.Error(), "read missing/Dockerfile: ") {
		t.Fatalf("expected a read error naming the path, got %v", err)
	}
}

func TestRewrite_reportsAMissingFile(t *testing.T) {
	refs := []Ref{{Path: "Dockerfile", Line: 1, Name: "oven/bun", Tag: "1", Digest: digestA}}

	err := Rewrite(t.TempDir(), refs, map[string]string{"oven/bun:1": digestB})

	if err == nil || !strings.HasPrefix(err.Error(), "read Dockerfile: ") {
		t.Fatalf("expected a read error naming the path, got %v", err)
	}
}
