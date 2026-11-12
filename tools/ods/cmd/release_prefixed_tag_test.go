package cmd

// Command states for the prefixed-tag releases (cli, ods, opal, tf-provider).
// Origin holds the release tags; the work clone has never fetched them, so a
// correct next version proves the targeted tag fetch.
//
//	P1 each target, --bump or --version      -> next tag on origin at HEAD      TestReleasePrefixedTag_pushesNextTag
//	P2 --dry-run                             -> no tag locally or on origin     TestReleasePrefixedTag_dryRunCreatesNothing
//	P3 no origin remote                      -> local tags used, push fails,
//	                                            local tag rolled back           TestReleasePrefixedTag_pushFailureRollsBackLocalTag
//	P4 --verify with a failing pre-push hook -> push fails, tag rolled back     TestReleasePrefixedTag_verifyRunsPrePushHook
//	P5 bad flags, no tags, existing tag      -> error, nothing created          TestReleasePrefixedTag_refusals

import (
	"io"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

type gitrelTagRepo struct {
	Origin string
	Work   string
	Head   string
}

// gitrelSetupTagRepo publishes main and pushes tags to origin only, then
// chdirs into the work clone.
func gitrelSetupTagRepo(t *testing.T, originTags ...string) gitrelTagRepo {
	t.Helper()
	origin, work := gittest.InitOriginAndWork(t)
	gittest.Git(t, work, "config", "tag.gpgSign", "false")
	gitrelHooks(t, work, nil)
	head := gitrelCommit(t, work, "a.txt", "a\n", "chore: base")
	gittest.PublishMain(t, work)
	for _, tag := range originTags {
		gittest.Git(t, work, "tag", tag)
		gittest.Git(t, work, "push", "--quiet", "origin", tag)
		gittest.Git(t, work, "tag", "-d", tag)
	}
	t.Chdir(work)
	return gitrelTagRepo{Origin: origin, Work: work, Head: head}
}

func TestReleasePrefixedTag_pushesNextTag(t *testing.T) {
	cases := []struct {
		name    string
		args    []string
		tags    []string
		wantTag string
	}{
		{"cli patch by default", []string{"cli", "--yes"}, []string{"cli/v1.2.3", "cli/v1.10.0", "cli/vbogus"}, "cli/v1.10.1"},
		{"ods minor", []string{"ods", "--yes", "--bump", "minor"}, []string{"ods/v0.4.7"}, "ods/v0.5.0"},
		{"opal major", []string{"opal", "--yes", "--bump", "major"}, []string{"opal/v2.3.4"}, "opal/v3.0.0"},
		{"tf-provider exact version", []string{"tf-provider", "--yes", "--version", "9.0.0"}, nil, "tf-provider/v9.0.0"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition. Tags of another target must not count.
			repo := gitrelSetupTagRepo(t, append(c.tags, "other/v50.0.0")...)
			cmd := NewReleaseCommand()
			cmd.SetArgs(c.args)
			cmd.SetOut(io.Discard)
			cmd.SetErr(io.Discard)

			// Under test.
			err := cmd.Execute()

			// Postcondition.
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if sha := gittest.Git(t, repo.Origin, "rev-parse", "refs/tags/"+c.wantTag); sha != repo.Head {
				t.Errorf("expected origin tag %s at %s, got %s", c.wantTag, repo.Head, sha)
			}
		})
	}
}

func TestReleasePrefixedTag_dryRunCreatesNothing(t *testing.T) {
	// Precondition.
	repo := gitrelSetupTagRepo(t, "opal/v1.0.0")

	// Under test.
	err := opalRelease.run(&prefixedTagOptions{Bump: "patch", DryRun: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gittest.TagExists(repo.Work, "opal/v1.0.1") || gittest.TagExists(repo.Origin, "opal/v1.0.1") {
		t.Error("dry run must not create the tag")
	}
}

func TestReleasePrefixedTag_pushFailureRollsBackLocalTag(t *testing.T) {
	// Precondition: no origin, so the fetch warns and the push fails.
	work := t.TempDir()
	gittest.Git(t, work, "init", "--quiet", "-b", "main")
	gittest.Git(t, work, "config", "user.email", "test@test.com")
	gittest.Git(t, work, "config", "user.name", "Test")
	gittest.Git(t, work, "config", "commit.gpgsign", "false")
	gittest.Git(t, work, "config", "tag.gpgSign", "false")
	gitrelHooks(t, work, nil)
	gitrelCommit(t, work, "a.txt", "a\n", "chore: base")
	gittest.Git(t, work, "tag", "cli/v1.0.0")
	t.Chdir(work)

	// Under test.
	err := cliRelease.run(&prefixedTagOptions{Bump: "patch", Yes: true})

	// Postcondition: the version came from the local tag.
	if err == nil || !strings.HasPrefix(err.Error(), "Failed to push tag cli/v1.0.1: ") {
		t.Fatalf("expected a push failure for cli/v1.0.1, got %v", err)
	}
	if gittest.TagExists(work, "cli/v1.0.1") {
		t.Error("local tag must be rolled back after a failed push")
	}
}

func TestReleasePrefixedTag_verifyRunsPrePushHook(t *testing.T) {
	// Precondition.
	repo := gitrelSetupTagRepo(t, "ods/v1.0.0")
	gitrelHooks(t, repo.Work, map[string]string{"pre-push": "#!/bin/sh\nexit 1\n"})

	// Under test.
	err := odsRelease.run(&prefixedTagOptions{Bump: "patch", Yes: true, Verify: true})

	// Postcondition.
	if err == nil || !strings.HasPrefix(err.Error(), "Failed to push tag ods/v1.0.1: ") {
		t.Fatalf("expected the hook to fail the push, got %v", err)
	}
	if gittest.TagExists(repo.Work, "ods/v1.0.1") || gittest.TagExists(repo.Origin, "ods/v1.0.1") {
		t.Error("expected no tag after the hook failed the push")
	}
}

func TestReleasePrefixedTag_refusals(t *testing.T) {
	cases := []struct {
		name    string
		tags    []string
		opts    prefixedTagOptions
		wantErr string
	}{
		{
			name:    "version with leading v",
			opts:    prefixedTagOptions{Version: "v1.2.3", Yes: true},
			wantErr: `--version must be X.Y.Z with no leading v, got "v1.2.3"`,
		},
		{
			name:    "unknown bump",
			opts:    prefixedTagOptions{Bump: "micro", Yes: true},
			wantErr: `--bump must be one of patch|minor|major, got "micro"`,
		},
		{
			name:    "no tags to bump",
			tags:    []string{"tf-provider/vnext"},
			opts:    prefixedTagOptions{Bump: "patch", Yes: true},
			wantErr: "Failed to determine the latest version (pass --version): no tf-provider/v* tags found",
		},
		{
			name:    "tag on origin already",
			tags:    []string{"tf-provider/v2.0.0"},
			opts:    prefixedTagOptions{Version: "2.0.0", Yes: true},
			wantErr: "Tag tf-provider/v2.0.0 already exists",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			repo := gitrelSetupTagRepo(t, c.tags...)

			// Under test.
			err := tfProviderRelease.run(&c.opts)

			// Postcondition.
			if err == nil || err.Error() != c.wantErr {
				t.Fatalf("expected %q, got %v", c.wantErr, err)
			}
			if out := gittest.Git(t, repo.Origin, "tag", "--list"); out != strings.Join(c.tags, "\n") {
				t.Errorf("expected origin tags unchanged, got %q", out)
			}
		})
	}
}
