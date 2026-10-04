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

func TestFetchTags_annotatedTagsFetchOnce(t *testing.T) {
	// Precondition: origin holds an annotated tag, which ls-remote lists twice
	// (the tag and its peeled "^{}" entry), and a lightweight tag.
	_, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	gittest.Git(t, work, "tag", "-a", "-m", "release", "v4.5.0", sha)
	gittest.Git(t, work, "tag", "v4.5.1", sha)
	gittest.Git(t, work, "push", "--quiet", "origin", "v4.5.0", "v4.5.1")
	gittest.Git(t, work, "tag", "-d", "v4.5.0", "v4.5.1")
	t.Chdir(work)

	// Under test: a refspec for the peeled entry would fail the fetch.
	if err := FetchTags("v4.5.*"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Postcondition.
	for _, tag := range []string{"v4.5.0", "v4.5.1"} {
		if !gittest.TagExists(work, tag) {
			t.Errorf("expected %s to be fetched", tag)
		}
	}
}

func TestSequencedTags_skipNumbersPastTheIntRange(t *testing.T) {
	// Precondition: tags whose numbers match the patterns but overflow an int.
	_, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	for _, tag := range []string{"v4.5.0", "v99999999999999999999.0.0", "v4.5.0-beta.0", "v4.5.0-beta.99999999999999999999"} {
		gittest.Git(t, work, "tag", tag, sha)
	}
	t.Chdir(work)

	// Under test.
	latest, err := LatestStableTag()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	next, err := nextSequencedTag("v4.5.0-beta.", "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Postcondition.
	if latest != "v4.5.0" {
		t.Errorf("expected %q, got %q", "v4.5.0", latest)
	}
	if next != "v4.5.0-beta.1" {
		t.Errorf("expected %q, got %q", "v4.5.0-beta.1", next)
	}
}
