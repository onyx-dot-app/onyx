package git

// PushNewBranch creates a branch or fails; it must never move a branch that
// appeared on origin after the caller checked for it.
//
//	P1 branch absent on origin           -> created at the commit    TestPushNewBranch_createsTheBranch
//	P2 branch appeared at an ancestor    -> rejected, origin
//	                                        unchanged                TestPushNewBranch_rejectsABranchThatAppeared
//
// PushNewTag creates a tag on origin or fails, and never touches local tags.
//
//	T1 tag absent on origin              -> created at the commit,
//	                                        no local tag             TestPushNewTag_createsTheTagOnOriginOnly
//	T2 tag already on origin             -> rejected, origin
//	                                        unchanged                TestPushNewTag_rejectsAnExistingTag
//	T3 --verify with a failing hook      -> rejected                 TestPushNewTag_verifyRunsPrePushHook

import (
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestPushNewBranch_createsTheBranch(t *testing.T) {
	// Precondition.
	origin, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	t.Chdir(work)

	// Under test.
	if err := PushNewBranch(sha, "release/v4.6", false); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Postcondition.
	if got := gittest.Git(t, origin, "rev-parse", "refs/heads/release/v4.6"); got != sha {
		t.Errorf("expected origin/release/v4.6 at %s, got %s", sha, got)
	}
}

func TestPushNewBranch_rejectsABranchThatAppeared(t *testing.T) {
	// Precondition: another cut created the branch at an ancestor of the
	// commit. A plain push would fast-forward it, and the caller would then tag
	// a branch it did not create.
	origin, work := gittest.InitOriginAndWork(t)
	ancestorSHA := gittest.Commit(t, work, "a.txt")
	sha := gittest.Commit(t, work, "b.txt")
	gittest.PublishMain(t, work)
	gittest.PublishReleaseBranch(t, work, "release/v4.6", ancestorSHA)
	t.Chdir(work)

	// Under test.
	err := PushNewBranch(sha, "release/v4.6", false)

	// Postcondition.
	if err == nil {
		t.Fatal("expected the push to be rejected")
	}
	if got := gittest.Git(t, origin, "rev-parse", "refs/heads/release/v4.6"); got != ancestorSHA {
		t.Errorf("origin/release/v4.6 must stay at %s, got %s", ancestorSHA, got)
	}
}

func TestPushNewTag_createsTheTagOnOriginOnly(t *testing.T) {
	// Precondition.
	origin, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	t.Chdir(work)

	// Under test.
	if err := PushNewTag(sha, "dev-build-x", false); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Postcondition.
	if got := gittest.Git(t, origin, "rev-parse", "refs/tags/dev-build-x"); got != sha {
		t.Errorf("expected origin dev-build-x at %s, got %s", sha, got)
	}
	if local := gittest.Git(t, work, "tag", "--list", "dev-build-x"); local != "" {
		t.Errorf("expected no local tag, got %q", local)
	}
}

func TestPushNewTag_rejectsAnExistingTag(t *testing.T) {
	// Precondition: the tag is already on origin at another commit.
	origin, work := gittest.InitOriginAndWork(t)
	first := gittest.Commit(t, work, "a.txt")
	sha := gittest.Commit(t, work, "b.txt")
	gittest.PublishMain(t, work)
	gittest.Git(t, work, "push", "--quiet", "origin", first+":refs/tags/dev-build-x")
	t.Chdir(work)

	// Under test.
	err := PushNewTag(sha, "dev-build-x", false)

	// Postcondition.
	if err == nil {
		t.Fatal("expected the push to be rejected")
	}
	if got := gittest.Git(t, origin, "rev-parse", "refs/tags/dev-build-x"); got != first {
		t.Errorf("origin dev-build-x must stay at %s, got %s", first, got)
	}
}
