package basedigest

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const digestA = "sha256:" + "aa" + "00000000000000000000000000000000000000000000000000000000000000"
const digestB = "sha256:" + "bb" + "00000000000000000000000000000000000000000000000000000000000000"
const digestC = "sha256:" + "cc" + "00000000000000000000000000000000000000000000000000000000000000"

// writeFile creates a file under a temporary root and returns the root.
func writeFile(t *testing.T, name, content string) string {
	t.Helper()
	root := t.TempDir()
	full := filepath.Join(root, name)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	if err := os.WriteFile(full, []byte(content), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	return root
}

func TestFindRefsParsesPrefixedAndBareReferences(t *testing.T) {
	root := writeFile(t, "Dockerfile", strings.Join([]string{
		"ARG BASE_IMAGE_REGISTRY=docker.io",
		"FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@" + digestA + " AS base",
		"FROM ghcr.io/astral-sh/uv:0.11.25@" + digestB,
	}, "\n"))

	refs, err := FindRefs(root, []string{"Dockerfile"})
	if err != nil {
		t.Fatalf("FindRefs: %v", err)
	}
	if len(refs) != 2 {
		t.Fatalf("got %d refs, want 2", len(refs))
	}

	if refs[0].Line != 2 || !refs[0].Prefixed {
		t.Errorf("first ref = line %d prefixed %v, want line 2 prefixed true", refs[0].Line, refs[0].Prefixed)
	}
	if got, want := refs[0].Query(), "docker.io/library/python:3.13-slim"; got != want {
		t.Errorf("Query() = %q, want %q", got, want)
	}
	if refs[1].Prefixed {
		t.Error("second ref should not be marked prefixed")
	}
	if got, want := refs[1].Query(), "ghcr.io/astral-sh/uv:0.11.25"; got != want {
		t.Errorf("Query() = %q, want %q", got, want)
	}
}

// A GitHub Actions `uses:` pin is a 40-hex commit sha, not a 64-hex digest, so it
// must not be mistaken for an image reference in the workflow files we scan.
func TestFindRefsIgnoresActionPins(t *testing.T) {
	root := writeFile(t, ".github/workflows/build.yml",
		"      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n")

	refs, err := FindRefs(root, []string{".github/workflows/build.yml"})
	if err != nil {
		t.Fatalf("FindRefs: %v", err)
	}
	if len(refs) != 0 {
		t.Fatalf("got %d refs, want 0: %+v", len(refs), refs)
	}
}

func TestFamilyGroupsPublicAndHardenedBases(t *testing.T) {
	cases := map[string]string{
		"library/python":       "python",
		"dhi.io/python":        "python",
		"python":               "python",
		"ghcr.io/astral-sh/uv": "uv",
		"oven/bun":             "bun",
	}
	for name, want := range cases {
		if got := (Ref{Name: name}).Family(); got != want {
			t.Errorf("Family(%q) = %q, want %q", name, got, want)
		}
	}
}

// Two references on one line must both be replaced, and the rewrite must touch
// only the digest bytes.
func TestRewriteReplacesOnlyDigests(t *testing.T) {
	const path = "Dockerfile"
	original := strings.Join([]string{
		"FROM ${BASE_IMAGE_REGISTRY}/library/node:24-trixie-slim@" + digestA + " AS builder",
		"# see oven/bun:1@" + digestB + " and library/node:24-trixie-slim@" + digestA,
		"",
	}, "\n")
	root := writeFile(t, path, original)

	refs, err := FindRefs(root, []string{path})
	if err != nil {
		t.Fatalf("FindRefs: %v", err)
	}
	resolved := map[string]string{
		"docker.io/library/node:24-trixie-slim": digestC,
		"library/node:24-trixie-slim":           digestC,
		"oven/bun:1":                            digestC,
	}
	if err := Rewrite(root, refs, resolved); err != nil {
		t.Fatalf("Rewrite: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(root, path))
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	want := strings.NewReplacer(digestA, digestC, digestB, digestC).Replace(original)
	if string(got) != want {
		t.Errorf("Rewrite produced:\n%s\nwant:\n%s", got, want)
	}
}

func TestStaleAndFamilyHelpers(t *testing.T) {
	refs := []Ref{
		{Name: "library/python", Tag: "3.13-slim", Digest: digestA},
		{Name: "dhi.io/python", Tag: "3.13-debian13", Digest: digestB},
		{Name: "oven/bun", Tag: "1", Digest: digestC},
	}
	resolved := map[string]string{
		"library/python:3.13-slim":    digestC, // moved
		"dhi.io/python:3.13-debian13": digestB, // current
		"oven/bun:1":                  digestC, // current
	}

	stale := Stale(refs, resolved)
	if len(stale) != 1 || stale[0].Name != "library/python" {
		t.Fatalf("Stale() = %+v, want only library/python", stale)
	}
	if got := Families(refs); len(got) != 2 || got[0] != "bun" || got[1] != "python" {
		t.Errorf("Families() = %v, want [bun python]", got)
	}
	if got := FilterFamily(refs, "python"); len(got) != 2 {
		t.Errorf("FilterFamily(python) returned %d refs, want 2", len(got))
	}
}

func TestSummaryTable(t *testing.T) {
	if got := SummaryTable(nil, nil); !strings.Contains(got, "current") {
		t.Errorf("empty SummaryTable() = %q, want a 'current' message", got)
	}

	refs := []Ref{{Path: "web/Dockerfile", Line: 7, Name: "oven/bun", Tag: "1", Digest: digestA}}
	got := SummaryTable(refs, map[string]string{"oven/bun:1": digestC})
	for _, want := range []string{"`oven/bun`", "`1`", "cc0000000000", "`web/Dockerfile:7`"} {
		if !strings.Contains(got, want) {
			t.Errorf("SummaryTable() = %q, missing %q", got, want)
		}
	}
}
