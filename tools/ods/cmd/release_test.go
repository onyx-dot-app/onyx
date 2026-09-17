package cmd

import (
	"io"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// gitrelExecuteRelease runs `ods release` with args and discards its output.
func gitrelExecuteRelease(args ...string) error {
	cmd := NewReleaseCommand()
	cmd.SetArgs(args)
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)
	return cmd.Execute()
}

func TestRelease_refWithoutCheckFails(t *testing.T) {
	// Precondition.
	gittest.SetupReleaseBranchRepo(t)

	// Under test.
	err := gitrelExecuteRelease("--ref", "v4.4.2")

	// Postcondition: a mistyped check must not exit 0 with help.
	if err == nil || err.Error() != "--ref requires --check" {
		t.Fatalf("expected %q, got %v", "--ref requires --check", err)
	}
}

func TestRelease_checkValidatesTheNamedTag(t *testing.T) {
	// Precondition: v4.4.2 skips v4.4.0 and v4.4.1.
	gittest.SetupReleaseBranchRepo(t)

	// Under test.
	err := gitrelExecuteRelease("--check", "--ref", "v4.4.2")

	// Postcondition.
	want := "tag v4.4.2 is out of sequence: without it, the next stable tag for v4.4 is v4.4.0"
	if err == nil || err.Error() != want {
		t.Fatalf("expected the check to reject v4.4.2, got %v", err)
	}
}
