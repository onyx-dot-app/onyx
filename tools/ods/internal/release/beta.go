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
		version, err := newestReleaseVersion()
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

// newestReleaseVersion returns the version of the newest release/vX.Y branch
// on origin.
func newestReleaseVersion() (Version, error) {
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
