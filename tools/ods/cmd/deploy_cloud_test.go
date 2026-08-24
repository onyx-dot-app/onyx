package cmd

// Command states for deployCloud. Tag computation and validation are tested
// in internal/release; these tests pin the command-level flow.
//
//	E1 dry run                               -> prints tag, creates nothing,
//	                                            returns no pushed tag           TestDeployCloud_dryRunCreatesNothing
//	E2 real run                              -> tag on origin at origin/main,
//	                                            tag name returned               TestDeployCloud_tagsOriginMainHead
//	E3 push rejected by origin               -> local tag rolled back,
//	                                            returns no pushed tag           TestDeployCloud_pushFailureRollsBackLocalTag
//	E4 counter tag only on origin            -> fetched, counter continues,
//	                                            tag name returned               TestDeployCloud_fetchesRemoteOnlyCounterTags
//	E5 --version with leading zeroes         -> rejected before any git work    TestDeployCloud_rejectsLeadingZeroVersion
//	E6 --attach with malformed or empty tag  -> rejected before any gh work     TestDeployCloud_attachRejectsMalformedTag
//	E7 --attach with a cut-flow flag         -> rejected before any gh work     TestDeployCloud_attachRejectsCutFlowFlags

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestDeployCloud_dryRunCreatesNothing(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	tag, err := deployCloud(&DeployCloudOptions{Ref: "origin/main", DryRun: true, Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "" {
		t.Errorf("dry run must return no pushed tag, got %q", tag)
	}
	if gittest.TagExists(repo.Work, "v4.6.0-cloud.0") || gittest.TagExists(repo.Origin, "v4.6.0-cloud.0") {
		t.Error("dry run must not create the tag")
	}
}

func TestDeployCloud_tagsOriginMainHead(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	tag, err := deployCloud(&DeployCloudOptions{Ref: "origin/main", Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.6.0-cloud.0" {
		t.Errorf("expected pushed tag v4.6.0-cloud.0, got %q", tag)
	}
	taggedSHA := gittest.Git(t, repo.Origin, "rev-parse", "refs/tags/v4.6.0-cloud.0^{commit}")
	if taggedSHA != repo.PostCutSHA {
		t.Errorf("expected origin tag at %s, got %s", repo.PostCutSHA, taggedSHA)
	}
}

func TestDeployCloud_fetchesRemoteOnlyCounterTags(t *testing.T) {
	// Precondition.
	// A counter tag another developer pushed but this clone never fetched.
	// Computing from local tags alone would mint a colliding v4.6.0-cloud.3.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.6.0-cloud.3", repo.PostCutSHA)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "v4.6.0-cloud.3")
	gittest.Git(t, repo.Work, "tag", "-d", "v4.6.0-cloud.3")

	// Under test.
	tag, err := deployCloud(&DeployCloudOptions{Ref: "origin/main", Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.6.0-cloud.4" {
		t.Errorf("expected pushed tag v4.6.0-cloud.4, got %q", tag)
	}
	if !gittest.TagExists(repo.Origin, "v4.6.0-cloud.4") {
		t.Error("expected v4.6.0-cloud.4 on origin")
	}
}

func TestDeployCloud_rejectsLeadingZeroVersion(t *testing.T) {
	// Precondition.
	// SemVer 2.0.0 item 2 forbids leading zeroes in numeric identifiers; such
	// an override must never become a tag.
	gittest.SetupReleaseBranchRepo(t)

	// Under test and postcondition.
	for _, version := range []string{"04.6.0", "4.06.0", "4.6.00"} {
		_, err := deployCloud(&DeployCloudOptions{Ref: "origin/main", Version: version, DryRun: true, Yes: true})
		if err == nil || !strings.Contains(err.Error(), "--version must be X.Y.Z") {
			t.Errorf("expected validation error for %q, got %v", version, err)
		}
	}
}

func TestDeployCloud_attachRejectsMalformedTag(t *testing.T) {
	// Under test and postcondition.
	// Leading zeroes are invalid per SemVer 2.0.0 item 2, and an explicit empty
	// tag (e.g. an unset shell variable) must fail validation instead of
	// falling through to the cut flow. Neither may reach the gh-backed watcher.
	for _, tag := range []string{"v4.7.0-cloud.01", ""} {
		cmd := NewDeployCloudCommand()
		cmd.SetOut(io.Discard)
		cmd.SetErr(io.Discard)
		cmd.SetArgs([]string{"--attach", tag})
		err := cmd.Execute()
		if err == nil || !strings.Contains(err.Error(), "is not a cloud tag") {
			t.Errorf("expected cloud tag validation error for %q, got %v", tag, err)
		}
	}
}

func TestDeployCloud_attachRejectsCutFlowFlags(t *testing.T) {
	// Under test and postcondition.
	// The malformed tag keeps a regressed clash check from reaching the
	// gh-backed watcher.
	for _, flag := range []string{"--ref=abc", "--version=5.0.0", "--dry-run", "--yes", "--verify", "--no-watch"} {
		cmd := NewDeployCloudCommand()
		cmd.SetOut(io.Discard)
		cmd.SetErr(io.Discard)
		cmd.SetArgs([]string{"--attach", "not-a-tag", flag})
		err := cmd.Execute()
		if err == nil || !strings.Contains(err.Error(), "--attach cannot be combined with") {
			t.Errorf("expected flag clash error for %s, got %v", flag, err)
		}
	}
}

func TestDeployCloud_pushFailureRollsBackLocalTag(t *testing.T) {
	// Precondition.
	// Origin rejects every push.
	repo := gittest.SetupReleaseBranchRepo(t)
	hook := filepath.Join(repo.Origin, "hooks", "pre-receive")
	if err := os.WriteFile(hook, []byte("#!/bin/sh\nexit 1\n"), 0755); err != nil {
		t.Fatal(err)
	}

	// Under test.
	tag, err := deployCloud(&DeployCloudOptions{Ref: "origin/main", Yes: true})

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "failed to push") {
		t.Errorf("expected push failure, got %v", err)
	}
	if tag != "" {
		t.Errorf("failed push must return no pushed tag, got %q", tag)
	}
	if gittest.TagExists(repo.Work, "v4.6.0-cloud.0") {
		t.Error("local tag must be rolled back after a failed push")
	}
}
