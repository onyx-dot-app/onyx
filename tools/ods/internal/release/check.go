package release

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

// betaTagRe matches a well-formed beta tag and captures its base version
// (with the leading v), the minor prefix ("X.Y"), and its counter. The legacy
// bare "-beta" form (last used by v3.2.0-beta) is deliberately not matched;
// new betas must carry a counter.
var betaTagRe = regexp.MustCompile(
	`^(v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\.(?:0|[1-9]\d*))-beta\.(0|[1-9]\d*)$`)

// CheckTag validates an existing release tag: a cloud tag against origin/main
// and its base derivation, a stable or beta tag against its release branch
// and counter sequence. ref may name the tag directly; otherwise the single
// release tag pointing at ref is checked.
func CheckTag(ref string) error {
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
	if betaTagRe.MatchString(tag) {
		return checkBetaTag(tag)
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
	// Unlike a cut (where origin rejects a colliding push), a check has no
	// backstop: stale local tags could pass an out-of-sequence tag.
	if err := FetchTags("v*-cloud.*"); err != nil {
		return fmt.Errorf("failed to fetch cloud tags: %w", err)
	}

	base := cloudTagRe.FindStringSubmatch(tag)[1]

	sha, err := ResolveCommit(tag)
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

	// Unlike a cut (where origin rejects a colliding push), a check has no
	// backstop: stale local tags could pass an out-of-sequence tag.
	if err := FetchTags(fmt.Sprintf("v%s.*", minor)); err != nil {
		return fmt.Errorf("failed to fetch v%s.* tags: %w", minor, err)
	}

	sha, err := ResolveCommit(tag)
	if err != nil {
		return err
	}

	if err := requireOnReleaseBranch(tag, sha, minor); err != nil {
		return err
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
		if err := requireAncestorTag(predecessor, tag, sha); err != nil {
			return err
		}
	}

	log.Infof("Tag %s is valid: it is on origin/release/v%s and the patch is in sequence.", tag, minor)
	return nil
}

// checkBetaTag validates an existing beta tag vX.Y.Z-beta.N: the tagged
// commit is on origin/release/vX.Y, the base vX.Y.Z has not shipped as a
// stable tag yet, the counter is one past the highest existing "-beta.N"
// counter for that base, and the predecessor beta is an ancestor of the
// tagged commit.
func checkBetaTag(tag string) error {
	matches := betaTagRe.FindStringSubmatch(tag)
	base := matches[1]  // "vX.Y.Z"
	minor := matches[2] // "X.Y"
	counter, err := strconv.Atoi(matches[3])
	if err != nil {
		return fmt.Errorf("failed to parse the counter of %s: %w", tag, err)
	}

	// Covers the base's betas and the stable base tag itself. Unlike a cut
	// (where origin rejects a colliding push), a check has no backstop:
	// stale local tags could pass an out-of-sequence tag.
	if err := FetchTags(base + "*"); err != nil {
		return fmt.Errorf("failed to fetch %s* tags: %w", base, err)
	}

	sha, err := ResolveCommit(tag)
	if err != nil {
		return err
	}

	if err := requireOnReleaseBranch(tag, sha, minor); err != nil {
		return err
	}

	// A beta precedes its stable release; a beta cut after the stable tag
	// shipped would also move the "beta" Docker tag backwards.
	if tagExists(base) {
		return fmt.Errorf("tag %s is a beta of %s, but %s has already been released", tag, base, base)
	}

	expected, err := nextSequencedTag(base+"-beta.", tag)
	if err != nil {
		return err
	}
	if tag != expected {
		return fmt.Errorf("tag %s is out of sequence: without it, the next beta tag for base %s is %s", tag, base, expected)
	}

	if counter > 0 {
		predecessor := fmt.Sprintf("%s-beta.%d", base, counter-1)
		if err := requireAncestorTag(predecessor, tag, sha); err != nil {
			return err
		}
	}

	log.Infof("Tag %s is valid: it is on origin/release/v%s and the counter is in sequence.", tag, minor)
	return nil
}

// requireOnReleaseBranch fetches origin/release/vX.Y for the minor ("X.Y")
// and errors unless sha is contained in it. Stable and beta tags are cut on
// their release branch.
func requireOnReleaseBranch(tag, sha, minor string) error {
	branch := fmt.Sprintf("release/v%s", minor)
	if err := git.RunCommand("fetch", "--quiet", "origin", BranchRefspec(branch)); err != nil {
		return fmt.Errorf("failed to fetch %s (stable and beta tags are cut on their release branch): %w", branch, err)
	}
	onBranch, err := git.IsAncestor(sha, "origin/"+branch)
	if err != nil {
		return err
	}
	if !onBranch {
		return fmt.Errorf("tag %s points at %.10s, which is not on origin/%s", tag, sha, branch)
	}
	return nil
}

// requireAncestorTag errors unless the predecessor tag is an ancestor of sha,
// the commit that tag points at.
func requireAncestorTag(predecessor, tag, sha string) error {
	isAncestor, err := git.IsAncestor(predecessor, sha)
	if err != nil {
		return err
	}
	if !isAncestor {
		return fmt.Errorf("predecessor tag %s is not an ancestor of %s", predecessor, tag)
	}
	return nil
}

// resolveReleaseTag returns ref itself when it names a well-formed cloud,
// stable, or beta tag, else the single such tag pointing at ref. More than
// one candidate is an error rather than a guess; pass the tag as ref to
// disambiguate.
func resolveReleaseTag(ref string) (string, error) {
	isReleaseTag := func(name string) bool {
		return cloudTagRe.MatchString(name) || stableTagRe.MatchString(name) || betaTagRe.MatchString(name)
	}
	if isReleaseTag(ref) {
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
		if isReleaseTag(name) {
			releaseTags = append(releaseTags, name)
		}
	}
	switch len(releaseTags) {
	case 0:
		return "", fmt.Errorf("no cloud (vX.Y.Z-cloud.N), stable (vX.Y.Z), or beta (vX.Y.Z-beta.N) tag points at %s", ref)
	case 1:
		return releaseTags[0], nil
	default:
		return "", fmt.Errorf("multiple release tags point at %s (%s); pass the one to check via --ref", ref, strings.Join(releaseTags, ", "))
	}
}
