package release

import (
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// gitFailureCalls runs each exported entry point once and returns its error.
var gitFailureCalls = []struct {
	name string
	call func() error
}{
	{"ComputeBetaTag", func() error { _, _, err := ComputeBetaTag("", "4.5.0"); return err }},
	{"ComputeNewBetaBranch", func() error { _, _, _, err := ComputeNewBetaBranch(""); return err }},
	{"ComputeCloudTag", func() error { _, err := ComputeCloudTag("HEAD", ""); return err }},
	{"FindTargetVersion", func() error { _, err := FindTargetVersion("HEAD"); return err }},
	{"CheckTag by name", func() error { return CheckTag("v4.5.0") }},
	{"CheckTag by ref", func() error { return CheckTag("HEAD") }},
	{"NewestReleaseVersion", func() error { _, err := NewestReleaseVersion(); return err }},
	{"FetchTags", func() error { return FetchTags("v*") }},
	{"LatestStableTag", func() error { _, err := LatestStableTag(); return err }},
	{"nextSequencedTag", func() error { _, err := nextSequencedTag("v4.5.", ""); return err }},
	{"Classify", func() error { _, err := Classify("v4.5.0", "abc", "push"); return err }},
}

// Outside a repository every git call fails. Each entry point must return
// that failure rather than treat it as "no tags" or "no branches".
func TestReleaseEntryPoints_outsideARepositoryError(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)

	wants := map[string]string{
		"ComputeBetaTag":       "is-shallow-repository failed",
		"ComputeNewBetaBranch": "is-shallow-repository failed",
		"ComputeCloudTag":      "is-shallow-repository failed",
		"FindTargetVersion":    "is-shallow-repository failed",
		"CheckTag by name":     "is-shallow-repository failed",
		"CheckTag by ref":      "git tag --points-at failed",
		"NewestReleaseVersion": "git ls-remote failed",
		"FetchTags":            "git ls-remote failed",
		"LatestStableTag":      "git tag --list failed",
		"nextSequencedTag":     "git tag --list failed",
		"Classify":             "failed to determine the highest stable tag",
	}
	for _, c := range gitFailureCalls {
		t.Run(c.name, func(t *testing.T) {
			want, ok := wants[c.name]
			if !ok {
				t.Fatalf("no expected error for %s", c.name)
			}
			if err := c.call(); err == nil || !strings.Contains(err.Error(), want) {
				t.Fatalf("expected %q, got %v", want, err)
			}
		})
	}
}

// Without git on PATH, commands fail to start. The errors still name the git
// command that failed.
func TestReleaseEntryPoints_gitMissingErrors(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	t.Chdir(t.TempDir())

	for _, c := range gitFailureCalls {
		t.Run(c.name, func(t *testing.T) {
			err := c.call()
			if err == nil || !strings.Contains(err.Error(), "git ") || !strings.Contains(err.Error(), exec.ErrNotFound.Error()) {
				t.Fatalf("expected a missing git error, got %v", err)
			}
		})
	}
}
