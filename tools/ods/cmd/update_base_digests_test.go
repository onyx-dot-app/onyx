package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/basedigest"
)

func shotDigest(c string) string {
	return "sha256:" + strings.Repeat(c, 64)
}

const (
	shotDockerfilePython = "docker.io/library/python:3.13-slim"
	shotDockerfileNode   = "node:22"
	shotWorkflowPython   = "dhi.io/python:3.13"
)

// shotDigestRepo creates a repository with three pinned references in two
// families, and a cache where only the Dockerfile python pin is stale.
func shotDigestRepo(t *testing.T) (root, cacheFile string) {
	t.Helper()
	root = shotGitRepo(t, map[string]string{
		"Dockerfile": "FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@" + shotDigest("a") + "\n" +
			"FROM node:22@" + shotDigest("b") + "\n",
		".github/workflows/ci.yml": "    image: dhi.io/python:3.13@" + shotDigest("c") + "\n",
		"README.md":                "node:22@" + shotDigest("e") + "\n",
	})
	cacheFile = filepath.Join(t.TempDir(), "digests.json")
	shotWriteCache(t, cacheFile, map[string]string{
		shotDockerfilePython: shotDigest("d"),
		shotDockerfileNode:   shotDigest("b"),
		shotWorkflowPython:   shotDigest("c"),
	})
	return root, cacheFile
}

func shotWriteCache(t *testing.T, path string, digests map[string]string) {
	t.Helper()
	data, err := json.Marshal(digests)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func shotReportLine(state, display, location string) string {
	return fmt.Sprintf("%7s  %-45s %s\n", state, display, location)
}

func TestRunUpdateBaseDigests_reportsWithoutWriting(t *testing.T) {
	root, cacheFile := shotDigestRepo(t)
	before, err := os.ReadFile(filepath.Join(root, "Dockerfile"))
	if err != nil {
		t.Fatal(err)
	}
	summaryFile := filepath.Join(t.TempDir(), "summary.md")

	output, err := runUpdateBaseDigests(false, summaryFile, "", false, cacheFile)
	if err != nil {
		t.Fatalf("runUpdateBaseDigests failed: %v", err)
	}

	want := shotReportLine("current", "dhi.io/python:3.13", ".github/workflows/ci.yml:1") +
		shotReportLine("update", "library/python:3.13-slim", "Dockerfile:1") +
		shotReportLine("current", "node:22", "Dockerfile:2") +
		"\n1 reference(s) are stale. Re-run with --write to apply.\n"
	if output != want {
		t.Fatalf("expected output:\n%s\ngot:\n%s", want, output)
	}
	if after, _ := os.ReadFile(filepath.Join(root, "Dockerfile")); string(after) != string(before) {
		t.Fatalf("expected the Dockerfile to stay unchanged, got:\n%s", after)
	}
	wantSummary := "| Image | Tag | New digest | File |\n| --- | --- | --- | --- |\n" +
		"| `library/python` | `3.13-slim` | `dddddddddddd` | `Dockerfile:1` |\n"
	if got := readShotFile(t, summaryFile); got != wantSummary {
		t.Fatalf("expected summary:\n%s\ngot:\n%s", wantSummary, got)
	}
}

func TestRunUpdateBaseDigests_writesOneFamily(t *testing.T) {
	root, cacheFile := shotDigestRepo(t)
	shotWriteCache(t, cacheFile, map[string]string{
		shotDockerfilePython: shotDigest("d"),
		shotDockerfileNode:   shotDigest("f"),
		shotWorkflowPython:   shotDigest("c"),
	})

	output, err := runUpdateBaseDigests(true, "", "python", false, cacheFile)
	if err != nil {
		t.Fatalf("runUpdateBaseDigests failed: %v", err)
	}

	want := shotReportLine("current", "dhi.io/python:3.13", ".github/workflows/ci.yml:1") +
		shotReportLine("update", "library/python:3.13-slim", "Dockerfile:1") +
		"\nUpdated 1 reference(s).\n"
	if output != want {
		t.Fatalf("expected output:\n%s\ngot:\n%s", want, output)
	}
	wantDockerfile := "FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@" + shotDigest("d") + "\n" +
		"FROM node:22@" + shotDigest("b") + "\n"
	if got := readShotFile(t, filepath.Join(root, "Dockerfile")); got != wantDockerfile {
		t.Fatalf("expected only the python pin to change, got:\n%s", got)
	}
}

func TestRunUpdateBaseDigests_listsStaleFamilies(t *testing.T) {
	_, cacheFile := shotDigestRepo(t)
	shotWriteCache(t, cacheFile, map[string]string{
		shotDockerfilePython: shotDigest("d"),
		shotDockerfileNode:   shotDigest("f"),
		shotWorkflowPython:   shotDigest("d"),
	})

	output, err := runUpdateBaseDigests(true, "", "", true, cacheFile)
	if err != nil {
		t.Fatalf("runUpdateBaseDigests failed: %v", err)
	}

	if output != "node\npython\n" {
		t.Fatalf("expected each stale family once, got %q", output)
	}
}

func TestRunUpdateBaseDigests_reportsAllCurrent(t *testing.T) {
	_, cacheFile := shotDigestRepo(t)
	shotWriteCache(t, cacheFile, map[string]string{
		shotDockerfilePython: shotDigest("a"),
		shotDockerfileNode:   shotDigest("b"),
		shotWorkflowPython:   shotDigest("c"),
	})
	summaryFile := filepath.Join(t.TempDir(), "summary.md")

	output, err := runUpdateBaseDigests(true, summaryFile, "node", false, cacheFile)
	if err != nil {
		t.Fatalf("runUpdateBaseDigests failed: %v", err)
	}

	want := shotReportLine("current", "node:22", "Dockerfile:2") + "\nAll pinned digests are current.\n"
	if output != want {
		t.Fatalf("expected output:\n%s\ngot:\n%s", want, output)
	}
	if got := readShotFile(t, summaryFile); got != "All pinned digests are current.\n" {
		t.Fatalf("expected the all-current summary, got %q", got)
	}
}

func TestRunUpdateBaseDigests_reportsFailures(t *testing.T) {
	tests := []struct {
		name  string
		setup func(t *testing.T, root, cacheFile string) (write bool, summaryFile, family string)
		want  string
		// wantOutput is the start of what the command prints before it fails.
		wantOutput string
	}{
		{
			name: "unknown family",
			setup: func(t *testing.T, root, cacheFile string) (bool, string, string) {
				return false, "", "golang"
			},
			want: `No references in family "golang".`,
		},
		{
			name: "corrupt cache",
			setup: func(t *testing.T, root, cacheFile string) (bool, string, string) {
				shotWriteFiles(t, filepath.Dir(cacheFile), map[string]string{filepath.Base(cacheFile): "{"})
				return false, "", ""
			},
			want: "Could not resolve every tag:\nread cache " + "<cache>" + ": unexpected end of JSON input",
		},
		{
			name: "deleted tracked file",
			setup: func(t *testing.T, root, cacheFile string) (bool, string, string) {
				if err := os.Remove(filepath.Join(root, "Dockerfile")); err != nil {
					t.Fatal(err)
				}
				return false, "", ""
			},
			want: "Could not read the tracked files: read Dockerfile: ",
		},
		{
			name: "invalid cached digest",
			setup: func(t *testing.T, root, cacheFile string) (bool, string, string) {
				shotWriteCache(t, cacheFile, map[string]string{
					shotDockerfilePython: "sha256:bad",
					shotDockerfileNode:   shotDigest("b"),
					shotWorkflowPython:   shotDigest("c"),
				})
				return true, "", ""
			},
			want:       `Could not rewrite the digests: refusing to write library/python:3.13-slim at Dockerfile:1: resolved digest "sha256:bad" is not valid`,
			wantOutput: shotReportLine("current", "dhi.io/python:3.13", ".github/workflows/ci.yml:1"),
		},
		{
			name: "unwritable summary",
			setup: func(t *testing.T, root, cacheFile string) (bool, string, string) {
				return false, t.TempDir(), ""
			},
			want:       "Could not write the summary: ",
			wantOutput: shotReportLine("current", "dhi.io/python:3.13", ".github/workflows/ci.yml:1"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			root, cacheFile := shotDigestRepo(t)
			write, summaryFile, family := tt.setup(t, root, cacheFile)
			want := strings.ReplaceAll(tt.want, "<cache>", cacheFile)

			output, err := runUpdateBaseDigests(write, summaryFile, family, false, cacheFile)

			if err == nil || !strings.HasPrefix(err.Error(), want) {
				t.Fatalf("expected %q, got %v", want, err)
			}
			if !strings.HasPrefix(output, tt.wantOutput) || (tt.wantOutput == "" && output != "") {
				t.Fatalf("expected output starting %q, got %q", tt.wantOutput, output)
			}
		})
	}
}

func TestRunUpdateBaseDigests_needsPinnedReferences(t *testing.T) {
	shotGitRepo(t, map[string]string{"Dockerfile": "FROM python:3.13\n"})

	_, err := runUpdateBaseDigests(false, "", "", false, "")

	if err == nil || err.Error() != "No pinned image references found." {
		t.Fatalf("expected the no-references error, got %v", err)
	}
}

func TestRunUpdateBaseDigests_needsARepository(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)

	_, err := runUpdateBaseDigests(false, "", "", false, "")

	if err == nil || !strings.HasPrefix(err.Error(), "Could not find the repository root: ") {
		t.Fatalf("expected the repository root error, got %v", err)
	}
}

func TestRunUpdateBaseDigests_reportsListFailure(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake git is a shell script")
	}
	binDir := t.TempDir()
	t.Setenv("ODS_TEST_GIT_ROOT", t.TempDir())
	script := "#!/bin/sh\ncase \"$1\" in rev-parse) echo \"$ODS_TEST_GIT_ROOT\" ;; *) exit 5 ;; esac\n"
	if err := os.WriteFile(filepath.Join(binDir, "git"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir+string(os.PathListSeparator)+os.Getenv("PATH"))

	_, err := runUpdateBaseDigests(false, "", "", false, "")

	if err == nil || err.Error() != "Could not list the tracked files: git ls-files: exit status 5" {
		t.Fatalf("expected the list error, got %v", err)
	}
}

func readShotFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func shotRegistryRefs(host string, tags ...string) []basedigest.Ref {
	refs := make([]basedigest.Ref, 0, len(tags))
	for _, tag := range tags {
		refs = append(refs, basedigest.Ref{Name: host + "/app", Tag: tag})
	}
	return refs
}

func TestResolveWithCache_writesAnAbsentCache(t *testing.T) {
	host, digests := shotFakeRegistry(t, "1", "2")
	cacheFile := filepath.Join(t.TempDir(), "digests.json")

	resolved, err := resolveWithCache(shotRegistryRefs(host, "1", "2", "1"), cacheFile)
	if err != nil {
		t.Fatalf("resolveWithCache failed: %v", err)
	}

	if fmt.Sprint(resolved) != fmt.Sprint(digests) {
		t.Fatalf("expected %v, got %v", digests, resolved)
	}
	wantCache, err := json.MarshalIndent(digests, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if got := readShotFile(t, cacheFile); got != string(wantCache)+"\n" {
		t.Fatalf("expected cache:\n%s\ngot:\n%s", wantCache, got)
	}
}

// Entries already in the cache are kept even if the registry has moved on, so
// every family in one run rewrites against the same snapshot.
func TestResolveWithCache_mergesAPartialCache(t *testing.T) {
	host, digests := shotFakeRegistry(t, "1", "2")
	cacheFile := filepath.Join(t.TempDir(), "digests.json")
	pinned := shotDigest("a")
	shotWriteCache(t, cacheFile, map[string]string{host + "/app:1": pinned})

	resolved, err := resolveWithCache(shotRegistryRefs(host, "1", "2"), cacheFile)
	if err != nil {
		t.Fatalf("resolveWithCache failed: %v", err)
	}

	want := map[string]string{host + "/app:1": pinned, host + "/app:2": digests[host+"/app:2"]}
	if fmt.Sprint(resolved) != fmt.Sprint(want) {
		t.Fatalf("expected %v, got %v", want, resolved)
	}
	var cached map[string]string
	if err := json.Unmarshal([]byte(readShotFile(t, cacheFile)), &cached); err != nil {
		t.Fatal(err)
	}
	if fmt.Sprint(cached) != fmt.Sprint(want) {
		t.Fatalf("expected the merged cache %v, got %v", want, cached)
	}
}

func TestResolveWithCache_usesAFullCacheAsIs(t *testing.T) {
	cacheFile := filepath.Join(t.TempDir(), "digests.json")
	// Not indented, so a rewrite would show.
	content := `{"example.invalid/app:1":"` + shotDigest("a") + `"}`
	shotWriteFiles(t, filepath.Dir(cacheFile), map[string]string{filepath.Base(cacheFile): content})

	resolved, err := resolveWithCache(shotRegistryRefs("example.invalid", "1"), cacheFile)
	if err != nil {
		t.Fatalf("resolveWithCache failed: %v", err)
	}

	if len(resolved) != 1 || resolved["example.invalid/app:1"] != shotDigest("a") {
		t.Fatalf("expected the cached digest, got %v", resolved)
	}
	if got := readShotFile(t, cacheFile); got != content {
		t.Fatalf("expected the cache to stay unchanged, got %s", got)
	}
}

func TestResolveWithCache_worksWithoutACacheFile(t *testing.T) {
	host, digests := shotFakeRegistry(t, "1")
	dir := t.TempDir()
	t.Chdir(dir)

	resolved, err := resolveWithCache(shotRegistryRefs(host, "1"), "")
	if err != nil {
		t.Fatalf("resolveWithCache failed: %v", err)
	}

	if fmt.Sprint(resolved) != fmt.Sprint(digests) {
		t.Fatalf("expected %v, got %v", digests, resolved)
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("expected no cache to be written, found %d entries", len(entries))
	}
}

func TestResolveWithCache_reportsFailures(t *testing.T) {
	host, _ := shotFakeRegistry(t, "1")
	dir := t.TempDir()
	missingDir := filepath.Join(dir, "missing", "digests.json")
	absent := filepath.Join(dir, "absent.json")

	tests := []struct {
		name      string
		tags      []string
		cacheFile string
		want      string
	}{
		{"cache is a directory", []string{"1"}, dir, "read cache " + dir + ": "},
		{"cache directory is missing", []string{"1"}, missingDir, "write cache " + missingDir + ": "},
		{"unknown tag", []string{"1", "nope"}, absent, "could not resolve " + host + "/app:nope: "},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			resolved, err := resolveWithCache(shotRegistryRefs(host, tt.tags...), tt.cacheFile)

			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
			if resolved != nil {
				t.Fatalf("expected no result, got %v", resolved)
			}
		})
	}
	if _, err := os.Stat(absent); !os.IsNotExist(err) {
		t.Fatalf("expected no cache after a failed resolve, got %v", err)
	}
}
