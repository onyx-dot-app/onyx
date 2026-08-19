package cmd

import (
	"fmt"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

// releaseBranchPattern matches maintained release branch names, e.g.
// "release/v4.5". Ad-hoc branches such as "release/v3.0-qa-f1df36e" are
// deliberately excluded.
var releaseBranchPattern = regexp.MustCompile(`^release/v(\d+)\.(\d+)$`)

// releaseBranchRefspec returns a forced fetch refspec that creates or updates
// the origin/<releaseBranch> tracking ref even in clones whose configured fetch
// refspec does not cover release branches (e.g. single-branch clones), where a
// plain "git fetch origin <branch>" only writes FETCH_HEAD.
func releaseBranchRefspec(releaseBranch string) string {
	return fmt.Sprintf("+refs/heads/%s:refs/remotes/origin/%s", releaseBranch, releaseBranch)
}

// releaseVersion is the parsed version of a "release/vX.Y" branch.
type releaseVersion struct {
	major int
	minor int
}

// String returns the version with its 'v' prefix, e.g. "v4.5".
func (v releaseVersion) String() string {
	return fmt.Sprintf("v%d.%d", v.major, v.minor)
}

// nextMinorBase returns the base version of the next minor release after this
// branch, e.g. v4.5 -> "v4.6.0".
func (v releaseVersion) nextMinorBase() string {
	return fmt.Sprintf("v%d.%d.0", v.major, v.minor+1)
}

// parseReleaseVersions extracts "release/vX.Y" versions from branch names and
// returns them sorted newest first. Names that do not match the pattern are
// ignored.
func parseReleaseVersions(branchNames []string) []releaseVersion {
	versions := []releaseVersion{}
	for _, name := range branchNames {
		matches := releaseBranchPattern.FindStringSubmatch(name)
		if matches == nil {
			continue
		}
		major, err := strconv.Atoi(matches[1])
		if err != nil {
			continue
		}
		minor, err := strconv.Atoi(matches[2])
		if err != nil {
			continue
		}
		versions = append(versions, releaseVersion{major: major, minor: minor})
	}
	sort.Slice(versions, func(i, j int) bool {
		if versions[i].major != versions[j].major {
			return versions[i].major > versions[j].major
		}
		return versions[i].minor > versions[j].minor
	})
	return versions
}

// listRemoteReleaseBranches returns the names (e.g. "release/v4.5") of all
// release branches on origin.
func listRemoteReleaseBranches() ([]string, error) {
	cmd := exec.Command("git", "ls-remote", "--heads", "origin", "release/*")
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("git ls-remote failed: %w: %s", err, string(exitErr.Stderr))
		}
		return nil, fmt.Errorf("git ls-remote failed: %w", err)
	}

	branches := []string{}
	for _, line := range strings.Split(string(output), "\n") {
		// Each line is "<sha>\trefs/heads/<branch>".
		_, ref, found := strings.Cut(line, "\t")
		if !found {
			continue
		}
		branches = append(branches, strings.TrimPrefix(strings.TrimSpace(ref), "refs/heads/"))
	}
	return branches, nil
}

// findTargetReleaseVersion returns the version (e.g. v4.5) of the newest
// "release/vX.Y" branch on origin that does not already contain commitSHA. A
// commit merged to main after the latest branch cut targets the newest branch;
// a commit that predates the cut (and is therefore already part of the newer
// branches) falls back to the newest branch actually missing it. Tags are
// deliberately not consulted: release tag names on main (e.g. "vX.Y.0-cloud.N")
// roll over to a new version asynchronously from the branch cut, so the nearest
// tag can disagree with the newest branch.
func findTargetReleaseVersion(commitSHA string) (releaseVersion, error) {
	// A shallow clone cannot answer ancestry truthfully: history beyond the
	// shallow boundary makes contained commits look uncontained, silently
	// routing them to the wrong branch. Fail loudly instead.
	shallow, err := git.IsShallowRepository()
	if err != nil {
		return releaseVersion{}, err
	}
	if shallow {
		return releaseVersion{}, fmt.Errorf("this is a shallow clone, so release auto-detection cannot check branch ancestry")
	}

	branchNames, err := listRemoteReleaseBranches()
	if err != nil {
		return releaseVersion{}, err
	}
	versions := parseReleaseVersions(branchNames)
	if len(versions) == 0 {
		return releaseVersion{}, fmt.Errorf("no release/vX.Y branches found on origin")
	}

	for _, version := range versions {
		releaseBranch := fmt.Sprintf("release/%s", version)
		// Fetch so the ancestry check runs against the branch's current tip.
		if err := git.RunCommand("fetch", "--quiet", "origin", releaseBranchRefspec(releaseBranch)); err != nil {
			return releaseVersion{}, fmt.Errorf("failed to fetch %s: %w", releaseBranch, err)
		}
		contained, err := git.IsAncestor(commitSHA, fmt.Sprintf("origin/%s", releaseBranch))
		if err != nil {
			return releaseVersion{}, err
		}
		if !contained {
			return version, nil
		}
		log.Infof("Commit %s is already contained in %s, checking the next older release branch", commitSHA, releaseBranch)
	}

	return releaseVersion{}, fmt.Errorf("commit %s is already contained in every release branch", commitSHA)
}
