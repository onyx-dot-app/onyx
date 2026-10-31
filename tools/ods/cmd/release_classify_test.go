package cmd

import (
	"io"
	"os"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestReleaseClassify_defaultsShaToHEAD(t *testing.T) {
	// Precondition: v4.4.2 is the only stable tag, so it is the latest.
	repo := gittest.SetupReleaseBranchRepo(t)
	cmd := NewReleaseClassifyCommand()
	cmd.SetArgs([]string{"--ref", "v4.4.2"})

	// Under test.
	var err error
	out := composeCapture(t, &os.Stdout, func() { err = cmd.Execute() })

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	for _, want := range []string{"is-stable=true\n", "is-latest=true\n", "short-sha=" + repo.PostCutSHA[:7] + "\n"} {
		if !strings.Contains(out, want) {
			t.Errorf("expected output to contain %q, got\n%s", want, out)
		}
	}
}

func TestReleaseClassify_failsOutsideARepository(t *testing.T) {
	cases := []struct {
		name    string
		args    []string
		wantErr string
	}{
		{"HEAD unresolvable", []string{"--ref", "v4.4.2"}, `failed to resolve "HEAD": `},
		{"stable tags unreadable", []string{"--ref", "v4.4.2", "--sha", "abc1234"}, "failed to determine the highest stable tag: "},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			gitrelChdirOutsideRepo(t)
			cmd := NewReleaseClassifyCommand()
			cmd.SetArgs(c.args)
			cmd.SetErr(io.Discard)

			// Under test.
			var err error
			out := composeCapture(t, &os.Stdout, func() { err = cmd.Execute() })

			// Postcondition.
			if err == nil || !strings.HasPrefix(err.Error(), c.wantErr) {
				t.Fatalf("expected an error starting with %q, got %v", c.wantErr, err)
			}
			if out != "" {
				t.Errorf("expected no output, got %q", out)
			}
		})
	}
}
