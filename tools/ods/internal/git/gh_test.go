package git

import (
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
)

// gitrelFakeGH puts a fake gh alone on PATH. body is the script after the
// shebang; the fake appends its arguments, one per line, to a record file.
// It returns a function that reads the recorded arguments.
func gitrelFakeGH(t *testing.T, body string) func() []string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake gh is a shell script")
	}
	dir := t.TempDir()
	record := filepath.Join(dir, "args")
	script := "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"${0%/*}/args\"\n" + body + "\n"
	if err := os.WriteFile(filepath.Join(dir, "gh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	return func() []string {
		data, err := os.ReadFile(record)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			t.Fatal(err)
		}
		return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
	}
}

func TestResolvePRToMergeCommit(t *testing.T) {
	cases := []struct {
		name    string
		body    string
		want    string
		wantErr string
	}{
		{name: "merged", body: "echo abc123", want: "abc123"},
		{name: "not merged", body: "echo null", wantErr: "PR #42 has no merge commit (is it merged?)"},
		{name: "empty", body: "true", wantErr: "PR #42 has no merge commit (is it merged?)"},
		{name: "gh fails", body: "echo 'not found' >&2; exit 1", wantErr: "gh pr view failed: exit status 1: not found\n"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			args := gitrelFakeGH(t, c.body)

			// Under test.
			got, err := ResolvePRToMergeCommit("42")

			// Postcondition.
			if c.wantErr != "" {
				if err == nil || err.Error() != c.wantErr {
					t.Fatalf("expected %q, got %v", c.wantErr, err)
				}
			} else if err != nil || got != c.want {
				t.Fatalf("expected %q, got %q, %v", c.want, got, err)
			}
			want := []string{"pr", "view", "42", "--json", "mergeCommit", "--jq", ".mergeCommit.oid"}
			if !slices.Equal(args(), want) {
				t.Errorf("expected args %q, got %q", want, args())
			}
		})
	}
}

func TestResolveCommitToPR(t *testing.T) {
	cases := []struct {
		name    string
		body    string
		want    string
		wantErr string
	}{
		{name: "found", body: "echo 7353", want: "7353"},
		{name: "no PR", body: "echo null", wantErr: "no associated PR found for commit abc123"},
		{name: "gh fails", body: "echo 'rate limited' >&2; exit 1", wantErr: "gh api commits/pulls failed: exit status 1: rate limited\n"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			args := gitrelFakeGH(t, c.body)

			// Under test.
			got, err := ResolveCommitToPR("abc123")

			// Postcondition.
			if c.wantErr != "" {
				if err == nil || err.Error() != c.wantErr {
					t.Fatalf("expected %q, got %v", c.wantErr, err)
				}
			} else if err != nil || got != c.want {
				t.Fatalf("expected %q, got %q, %v", c.want, got, err)
			}
			want := []string{"api", "repos/{owner}/{repo}/commits/abc123/pulls", "--jq", ".[0].number"}
			if !slices.Equal(args(), want) {
				t.Errorf("expected args %q, got %q", want, args())
			}
		})
	}
}

func TestGHLookups_withoutGH(t *testing.T) {
	// Precondition: PATH holds no gh.
	t.Setenv("PATH", t.TempDir())

	// Under test and postcondition.
	if _, err := ResolvePRToMergeCommit("42"); err == nil || !strings.HasPrefix(err.Error(), "gh pr view failed: exec: ") {
		t.Errorf("expected a missing gh error, got %v", err)
	}
	if _, err := ResolveCommitToPR("abc123"); err == nil || !strings.HasPrefix(err.Error(), "gh api commits/pulls failed: exec: ") {
		t.Errorf("expected a missing gh error, got %v", err)
	}
}

func TestDispatchCherryPickWorkflow(t *testing.T) {
	t.Run("all inputs", func(t *testing.T) {
		args := gitrelFakeGH(t, "")
		if err := DispatchCherryPickWorkflow("abc123", "42", "v4.5", false); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		want := []string{"workflow", "run", "post-merge-beta-cherry-pick.yml", "-f", "merge_commit_sha=abc123", "-f", "pr_number=42", "-f", "release=v4.5"}
		if !slices.Equal(args(), want) {
			t.Errorf("expected args %q, got %q", want, args())
		}
	})

	t.Run("optional inputs omitted", func(t *testing.T) {
		args := gitrelFakeGH(t, "")
		if err := DispatchCherryPickWorkflow("abc123", "", "", false); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		want := []string{"workflow", "run", "post-merge-beta-cherry-pick.yml", "-f", "merge_commit_sha=abc123"}
		if !slices.Equal(args(), want) {
			t.Errorf("expected args %q, got %q", want, args())
		}
	})

	t.Run("dry run runs nothing", func(t *testing.T) {
		args := gitrelFakeGH(t, "")
		if err := DispatchCherryPickWorkflow("abc123", "42", "v4.5", true); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got := args(); got != nil {
			t.Errorf("expected no gh call, got %q", got)
		}
	})

	t.Run("failure carries the output", func(t *testing.T) {
		gitrelFakeGH(t, "echo '  HTTP 404: workflow not found  '; exit 1")
		err := DispatchCherryPickWorkflow("abc123", "", "", false)
		if err == nil || err.Error() != "exit status 1: HTTP 404: workflow not found" {
			t.Errorf("expected the trimmed output, got %v", err)
		}
	})

	t.Run("silent failure", func(t *testing.T) {
		gitrelFakeGH(t, "exit 2")
		err := DispatchCherryPickWorkflow("abc123", "", "", false)
		if err == nil || err.Error() != "exit status 2" {
			t.Errorf("expected exit status 2, got %v", err)
		}
	})
}
