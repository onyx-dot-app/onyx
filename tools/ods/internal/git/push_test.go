package git

// PushNewBranch creates a branch or fails; it must never move a branch that
// appeared on origin after the caller checked for it.
//
//	P1 branch absent on origin           -> created at the commit    TestPushNewBranch_createsTheBranch
//	P2 branch appeared at an ancestor    -> rejected, origin
//	                                        unchanged                TestPushNewBranch_rejectsABranchThatAppeared

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
