package release

import (
	"fmt"
	"strconv"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

// ComputeBetaTag returns the next beta tag (vX.Y.Z-beta.N) and the commit it
// should point at. With overrideVersion ("X.Y.Z") the base is fixed and its
// release branch is the target; otherwise the target is the newest
// release/vX.Y branch on origin and the base is one patch past the highest
// stable vX.Y.* tag. ref is the commit-ish to tag; when empty, the branch tip
// is used. The commit must be on the branch, the base must not have shipped
// as a stable tag, and the predecessor beta (if any) must be an ancestor of
// the commit — the same policy "ods release --check" enforces.
func ComputeBetaTag(ref, overrideVersion string) (tag, sha string, err error) {
	// The ancestry checks below cannot be answered truthfully in a shallow
	// clone; fail loudly instead.
	shallow, err := git.IsShallowRepository()
	if err != nil {
		return "", "", err
	}
	if shallow {
		return "", "", fmt.Errorf("this is a shallow clone, so beta tag computation cannot check branch ancestry")
	}

	var minor string // "X.Y"
	if overrideVersion != "" {
		matches := bareSemverRe.FindStringSubmatch(overrideVersion)
		if matches == nil {
			return "", "", fmt.Errorf("override version must be X.Y.Z with no leading v, got %q", overrideVersion)
		}
		minor = matches[1] + "." + matches[2]
	} else {
		version, err := NewestReleaseVersion()
		if err != nil {
			return "", "", fmt.Errorf("failed to detect the target release branch (pass --version to override): %w", err)
		}
		minor = fmt.Sprintf("%d.%d", version.Major, version.Minor)
		log.Infof("Newest release branch on origin: release/v%s", minor)
	}

	branch := fmt.Sprintf("release/v%s", minor)
	// Fetch so the tip default and the ancestry check run against the branch's
	// current state; a missing branch fails here.
	if err := git.RunCommand("fetch", "--quiet", "origin", BranchRefspec(branch)); err != nil {
		return "", "", fmt.Errorf("failed to fetch %s (beta tags are cut on their release branch): %w", branch, err)
	}

	if ref == "" {
		ref = "origin/" + branch
	}
	sha, err = ResolveCommit(ref)
	if err != nil {
		return "", "", err
	}

	onBranch, err := git.IsAncestor(sha, "origin/"+branch)
	if err != nil {
		return "", "", err
	}
	if !onBranch {
		return "", "", fmt.Errorf("commit %.10s is not on origin/%s; beta tags are cut on their release branch", sha, branch)
	}

	// The base derives from the minor's stable tags, and a beta of an
	// already-released base is itself a new tag: origin would accept the push
	// and only CI's check would reject it. Unlike a counter collision there is
	// no push backstop, so a failed fetch is an error, not a stale-tags
	// fallback.
	if err := FetchTags(fmt.Sprintf("v%s.*", minor)); err != nil {
		return "", "", fmt.Errorf("failed to fetch v%s.* tags: %w", minor, err)
	}

	var base string
	if overrideVersion != "" {
		base = "v" + overrideVersion
		// A beta precedes its stable release; a beta cut after the stable tag
		// shipped would also move the "beta" Docker tag backwards.
		if tagExists(base) {
			return "", "", fmt.Errorf("%s has already been released; a beta must precede its stable tag", base)
		}
	} else {
		base, err = nextSequencedTag(fmt.Sprintf("v%s.", minor), "")
		if err != nil {
			return "", "", err
		}
		log.Infof("Next unreleased patch on release/v%s -> beta base %s", minor, base)
	}

	tag, err = nextSequencedTag(base+"-beta.", "")
	if err != nil {
		return "", "", err
	}

	// The check also requires the predecessor beta to be an ancestor; catching
	// that here keeps a doomed tag from being pushed (e.g. --ref pointing
	// below the previous beta).
	counter, err := strconv.Atoi(betaTagRe.FindStringSubmatch(tag)[3])
	if err != nil {
		return "", "", fmt.Errorf("failed to parse the counter of %s: %w", tag, err)
	}
	if counter > 0 {
		predecessor := fmt.Sprintf("%s-beta.%d", base, counter-1)
		if err := requireAncestorTag(predecessor, tag, sha); err != nil {
			return "", "", err
		}
	}

	return tag, sha, nil
}

// ComputeNewBetaBranch returns the release branch to create for the next minor
// release, the first beta tag to cut on it, and the commit both should point
// at. The branch is one minor past the newest release/vX.Y branch on origin —
// the version cloud tags of main already preview — and it is cut from
// origin/main. ref is the commit-ish to cut at; when empty, the main tip is
// used. The commit must be on origin/main, the new branch must not exist on
// origin yet, and its base must not have shipped as a stable tag.
func ComputeNewBetaBranch(ref string) (branch, tag, sha string, err error) {
	// The ancestry check below cannot be answered truthfully in a shallow
	// clone; fail loudly instead.
	shallow, err := git.IsShallowRepository()
	if err != nil {
		return "", "", "", err
	}
	if shallow {
		return "", "", "", fmt.Errorf("this is a shallow clone, so a release branch cut cannot check main ancestry")
	}

	branchNames, err := listRemoteBranches()
	if err != nil {
		return "", "", "", err
	}
	versions := parseVersions(branchNames)
	if len(versions) == 0 {
		return "", "", "", fmt.Errorf("no release/vX.Y branches found on origin, so the next minor cannot be derived")
	}
	version := versions[0].NextMinor()
	branch = fmt.Sprintf("release/%s", version)
	for _, name := range branchNames {
		if name == branch {
			return "", "", "", fmt.Errorf("%s already exists on origin; re-run without --new-branch to cut its next beta", branch)
		}
	}
	log.Infof("Newest release branch on origin: release/%s -> new branch %s", versions[0], branch)

	// Cut points come from main, so the tip default and the ancestry check must
	// run against its current state.
	if err := git.RunCommand("fetch", "--quiet", "--force", "origin", "+refs/heads/main:refs/remotes/origin/main"); err != nil {
		return "", "", "", fmt.Errorf("failed to fetch origin/main: %w", err)
	}
	if ref == "" {
		ref = "origin/main"
	}
	sha, err = ResolveCommit(ref)
	if err != nil {
		return "", "", "", err
	}
	onMain, err := git.IsAncestor(sha, "origin/main")
	if err != nil {
		return "", "", "", err
	}
	if !onMain {
		return "", "", "", fmt.Errorf("commit %.10s is not on origin/main; release branches are cut from main", sha)
	}

	// A beta of an already-released base is itself a new tag: origin would
	// accept the push and only CI's check would reject it, so a failed fetch is
	// an error rather than a stale-tags fallback.
	base := version.String() + ".0"
	if err := FetchTags(base + "*"); err != nil {
		return "", "", "", fmt.Errorf("failed to fetch %s* tags: %w", base, err)
	}
	if tagExists(base) {
		return "", "", "", fmt.Errorf("%s has already been released; a beta must precede its stable tag", base)
	}
	tag, err = nextSequencedTag(base+"-beta.", "")
	if err != nil {
		return "", "", "", err
	}
	// A fresh branch has no predecessor beta to anchor to, so betas of the base
	// without the branch mean an earlier cut half-succeeded or the branch was
	// deleted; both need a human.
	if tag != base+"-beta.0" {
		return "", "", "", fmt.Errorf("betas of %s already exist but %s does not, so the next tag would be %s with no branch to anchor it; resolve the branch state first", base, branch, tag)
	}

	return branch, tag, sha, nil
}

// NewestReleaseVersion returns the version of the newest release/vX.Y branch
// on origin.
func NewestReleaseVersion() (Version, error) {
	branchNames, err := listRemoteBranches()
	if err != nil {
		return Version{}, err
	}
	versions := parseVersions(branchNames)
	if len(versions) == 0 {
		return Version{}, fmt.Errorf("no release/vX.Y branches found on origin")
	}
	return versions[0], nil
}
