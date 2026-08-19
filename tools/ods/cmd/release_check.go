package cmd

import (
	"fmt"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

// stableTagRe matches a well-formed stable tag (vX.Y.Z, no pre-release
// suffix) and captures the minor prefix ("X.Y") and the patch number.
var stableTagRe = regexp.MustCompile(
	`^v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\.(0|[1-9]\d*)$`)

// checkReleaseTag validates an existing release tag: a cloud tag against
// origin/main and its base derivation, a stable tag against its release
// branch and patch sequence. ref may name the tag directly; otherwise the
// single cloud or stable tag pointing at ref is checked.
func checkReleaseTag(ref string) error {
	tag, err := resolveReleaseTag(ref)
	if err != nil {
		return err
	}

	// Ancestry cannot be answered truthfully in a shallow clone.
	shallow, err := git.IsShallowRepository()
	if err != nil {
		return err
	}
	if shallow {
		return fmt.Errorf("this is a shallow clone, so the release tag check cannot verify ancestry")
	}

	if cloudTagRe.MatchString(tag) {
		return checkCloudTag(tag)
	}
	return checkStableTag(tag)
}

// checkCloudTag validates that an existing cloud tag is the tag `ods release
// cloud` would have computed for its commit: the commit is on origin/main,
// the base matches the release-branch derivation, and the counter is exactly
// one past the previous counter for that base.
func checkCloudTag(tag string) error {
	// The base derivation and ancestry run against origin's current state.
	if err := git.RunCommand("fetch", "--quiet", "--force", "origin", "+refs/heads/main:refs/remotes/origin/main"); err != nil {
		return fmt.Errorf("failed to fetch origin/main: %w", err)
	}
	// Best-effort: stale local tags can only mis-report the sequence, which
	// the error message makes visible.
	if err := fetchTags("v*-cloud.*"); err != nil {
		log.Warnf("Could not fetch cloud tags (using local tags): %v", err)
	}

	base := cloudTagRe.FindStringSubmatch(tag)[1]

	sha, err := resolveCommit(tag)
	if err != nil {
		return err
	}

	expectedBase, err := computeCloudBase(sha, "")
	if err != nil {
		return err
	}
	if base != expectedBase {
		return fmt.Errorf("tag %s has base %s, but the expected base for commit %.10s is %s", tag, base, sha, expectedBase)
	}

	expected, err := nextSequencedTag(base+"-cloud.", tag)
	if err != nil {
		return err
	}
	if tag != expected {
		return fmt.Errorf("tag %s is out of sequence: without it, the next cloud tag for base %s is %s", tag, base, expected)
	}

	log.Infof("Tag %s is valid: base %s matches commit %.10s and the counter is in sequence.", tag, base, sha)
	return nil
}

// checkStableTag validates an existing stable tag vX.Y.Z: the tagged commit
// is on origin/release/vX.Y, the patch is one past the highest existing
// vX.Y.* patch, and the predecessor patch is an ancestor of the tagged
// commit.
func checkStableTag(tag string) error {
	matches := stableTagRe.FindStringSubmatch(tag)
	minor := matches[1] // "X.Y"
	patch, err := strconv.Atoi(matches[2])
	if err != nil {
		return fmt.Errorf("failed to parse the patch number of %s: %w", tag, err)
	}

	// Best-effort, as for cloud tags: stale local tags can only mis-report
	// the sequence, which the error message makes visible.
	if err := fetchTags(fmt.Sprintf("v%s.*", minor)); err != nil {
		log.Warnf("Could not fetch v%s.* tags (using local tags): %v", minor, err)
	}

	sha, err := resolveCommit(tag)
	if err != nil {
		return err
	}

	branch := fmt.Sprintf("release/v%s", minor)
	if err := git.RunCommand("fetch", "--quiet", "origin", releaseBranchRefspec(branch)); err != nil {
		return fmt.Errorf("failed to fetch %s (stable tags are cut on their release branch): %w", branch, err)
	}
	onBranch, err := git.IsAncestor(sha, "origin/"+branch)
	if err != nil {
		return err
	}
	if !onBranch {
		return fmt.Errorf("tag %s points at %.10s, which is not on origin/%s", tag, sha, branch)
	}

	expected, err := nextSequencedTag(fmt.Sprintf("v%s.", minor), tag)
	if err != nil {
		return err
	}
	if tag != expected {
		return fmt.Errorf("tag %s is out of sequence: without it, the next stable tag for v%s is %s", tag, minor, expected)
	}

	if patch > 0 {
		predecessor := fmt.Sprintf("v%s.%d", minor, patch-1)
		isAncestor, err := git.IsAncestor(predecessor, sha)
		if err != nil {
			return err
		}
		if !isAncestor {
			return fmt.Errorf("predecessor tag %s is not an ancestor of %s", predecessor, tag)
		}
	}

	log.Infof("Tag %s is valid: it is on origin/%s and the patch is in sequence.", tag, branch)
	return nil
}

// resolveReleaseTag returns ref itself when it names a well-formed cloud or
// stable tag, else the single such tag pointing at ref. More than one
// candidate is an error rather than a guess; pass the tag as ref to
// disambiguate.
func resolveReleaseTag(ref string) (string, error) {
	if cloudTagRe.MatchString(ref) || stableTagRe.MatchString(ref) {
		return ref, nil
	}

	out, err := exec.Command("git", "tag", "--points-at", ref).Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && len(exitErr.Stderr) > 0 {
			return "", fmt.Errorf("git tag --points-at failed: %w: %s", err, strings.TrimSpace(string(exitErr.Stderr)))
		}
		return "", fmt.Errorf("git tag --points-at failed: %w", err)
	}

	releaseTags := []string{}
	for _, line := range strings.Split(string(out), "\n") {
		name := strings.TrimSpace(line)
		if cloudTagRe.MatchString(name) || stableTagRe.MatchString(name) {
			releaseTags = append(releaseTags, name)
		}
	}
	switch len(releaseTags) {
	case 0:
		return "", fmt.Errorf("no cloud (vX.Y.Z-cloud.N) or stable (vX.Y.Z) tag points at %s", ref)
	case 1:
		return releaseTags[0], nil
	default:
		return "", fmt.Errorf("multiple release tags point at %s (%s); pass the one to check via --ref", ref, strings.Join(releaseTags, ", "))
	}
}
