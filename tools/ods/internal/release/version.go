// Package release implements Onyx's release tag policy: how cloud, stable,
// and beta tags are named, sequenced, and anchored to release branches, plus
// validation of existing tags against that policy. Commands under cmd/ stay
// thin cobra wiring over this package.
package release

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

// bareSemverRe matches a bare X.Y.Z version (no leading v). Leading zeroes are
// rejected per SemVer 2.0.0 item 2.
var bareSemverRe = regexp.MustCompile(`^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`)

// IsBareVersion reports whether s is a bare X.Y.Z version (no leading v).
func IsBareVersion(s string) bool {
	return bareSemverRe.MatchString(s)
}

// branchRe matches maintained release branch names, e.g. "release/v4.5".
// Ad-hoc branches such as "release/v3.0-qa-f1df36e" are deliberately excluded.
var branchRe = regexp.MustCompile(`^release/v(\d+)\.(\d+)$`)

// BranchRefspec returns a forced fetch refspec that creates or updates the
// origin/<releaseBranch> tracking ref even in clones whose configured fetch
// refspec does not cover release branches (e.g. single-branch clones), where a
// plain "git fetch origin <branch>" only writes FETCH_HEAD.
func BranchRefspec(releaseBranch string) string {
	return fmt.Sprintf("+refs/heads/%s:refs/remotes/origin/%s", releaseBranch, releaseBranch)
}

// Version is the parsed version of a "release/vX.Y" branch.
type Version struct {
	Major int
	Minor int
}

// String returns the version with its 'v' prefix, e.g. "v4.5".
func (v Version) String() string {
	return fmt.Sprintf("v%d.%d", v.Major, v.Minor)
}

// NextMinorBase returns the base version of the next minor release after this
// branch, e.g. v4.5 -> "v4.6.0".
func (v Version) NextMinorBase() string {
	return fmt.Sprintf("v%d.%d.0", v.Major, v.Minor+1)
}

// parseVersions extracts "release/vX.Y" versions from branch names and
// returns them sorted newest first. Names that do not match the pattern are
// ignored.
func parseVersions(branchNames []string) []Version {
	versions := []Version{}
	for _, name := range branchNames {
		matches := branchRe.FindStringSubmatch(name)
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
		versions = append(versions, Version{Major: major, Minor: minor})
	}
	sort.Slice(versions, func(i, j int) bool {
		if versions[i].Major != versions[j].Major {
			return versions[i].Major > versions[j].Major
		}
		return versions[i].Minor > versions[j].Minor
	})
	return versions
}

// listRemoteBranches returns the names (e.g. "release/v4.5") of all release
// branches on origin.
func listRemoteBranches() ([]string, error) {
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

// FindTargetVersion returns the version (e.g. v4.5) of the newest
// "release/vX.Y" branch on origin that does not already contain commitSHA. A
// commit merged to main after the latest branch cut targets the newest branch;
// a commit that predates the cut (and is therefore already part of the newer
// branches) falls back to the newest branch actually missing it. Tags are
// deliberately not consulted: release tag names on main (e.g. "vX.Y.0-cloud.N")
// roll over to a new version asynchronously from the branch cut, so the nearest
// tag can disagree with the newest branch.
func FindTargetVersion(commitSHA string) (Version, error) {
	// A shallow clone cannot answer ancestry truthfully: history beyond the
	// shallow boundary makes contained commits look uncontained, silently
	// routing them to the wrong branch. Fail loudly instead.
	shallow, err := git.IsShallowRepository()
	if err != nil {
		return Version{}, err
	}
	if shallow {
		return Version{}, fmt.Errorf("this is a shallow clone, so release auto-detection cannot check branch ancestry")
	}

	branchNames, err := listRemoteBranches()
	if err != nil {
		return Version{}, err
	}
	versions := parseVersions(branchNames)
	if len(versions) == 0 {
		return Version{}, fmt.Errorf("no release/vX.Y branches found on origin")
	}

	for _, version := range versions {
		releaseBranch := fmt.Sprintf("release/%s", version)
		// Fetch so the ancestry check runs against the branch's current tip.
		if err := git.RunCommand("fetch", "--quiet", "origin", BranchRefspec(releaseBranch)); err != nil {
			return Version{}, fmt.Errorf("failed to fetch %s: %w", releaseBranch, err)
		}
		contained, err := git.IsAncestor(commitSHA, fmt.Sprintf("origin/%s", releaseBranch))
		if err != nil {
			return Version{}, err
		}
		if !contained {
			return version, nil
		}
		log.Infof("Commit %s is already contained in %s, checking the next older release branch", commitSHA, releaseBranch)
	}

	return Version{}, fmt.Errorf("commit %s is already contained in every release branch", commitSHA)
}
