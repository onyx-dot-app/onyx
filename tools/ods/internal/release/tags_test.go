package release

import (
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestLatestStableTag_ordersNumericallyAndSkipsPreReleases(t *testing.T) {
	// Precondition: v4.9.0 outranks v4.10.0 lexically, and the newest tags of
	// all are pre-releases that must not win.
	_, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	for _, tag := range []string{
		"v4.9.0", "v4.10.0", "v4.10.1", // Numeric vs lexical ordering.
		"v4.11.0-beta.1", "v4.11.0-cloud.2", // Pre-releases outrank every stable tag.
		"v4.10.02", "release-4.20", // Malformed names.
	} {
		gittest.Git(t, work, "tag", tag, sha)
	}
	t.Chdir(work)

	// Under test.
	tag, err := LatestStableTag()

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.10.1" {
		t.Errorf("expected v4.10.1, got %s", tag)
	}
}

func TestLatestStableTag_noStableTags(t *testing.T) {
	// Precondition: a repo whose only tag is a pre-release.
	_, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	gittest.Git(t, work, "tag", "v4.11.0-beta.1", sha)
	t.Chdir(work)

	// Under test.
	tag, err := LatestStableTag()

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "" {
		t.Errorf("expected no tag, got %s", tag)
	}
}
