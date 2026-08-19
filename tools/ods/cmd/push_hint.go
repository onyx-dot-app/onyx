package cmd

import (
	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

// pushWithHookHint runs a branch push. If the hooks are enabled and the push is
// slow, it tells the user about --no-verify.
func pushWithHookHint(noVerify bool, push func() error) error {
	if noVerify {
		return push()
	}
	hint := "Push is slow because the pre-push hooks are running. Re-run with --no-verify to skip them."
	return git.HintAfter(git.PushHookHintDelay, hint, push)
}
