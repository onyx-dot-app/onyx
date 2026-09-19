package release

import (
	"fmt"
	"regexp"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

// cloudTagRe matches a well-formed cloud tag and captures its base version
// (with the leading v) and its counter. Leading zeroes are rejected per SemVer
// 2.0.0 item 2.
var cloudTagRe = regexp.MustCompile(
	`^(v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))-cloud\.(0|[1-9]\d*)$`)

// IsCloudTag reports whether s is a complete cloud tag, e.g. "v4.7.0-cloud.3".
func IsCloudTag(s string) bool {
	return cloudTagRe.MatchString(s)
}

// ComputeCloudTag returns the next cloud tag for commitSHA. The base version
// is "v" + overrideVersion when given, else one minor past the newest release
// branch on origin that does not contain the commit; the counter is one past
// the highest existing "-cloud.N" tag for that base.
func ComputeCloudTag(commitSHA, overrideVersion string) (string, error) {
	base, err := computeCloudBase(commitSHA, overrideVersion)
	if err != nil {
		return "", err
	}
	return nextSequencedTag(base+"-cloud.", "")
}

// computeCloudBase returns the cloud base version (e.g. "v4.6.0") for
// commitSHA: "v" + overrideVersion when given, else one minor past the newest
// release branch on origin that does not contain the commit.
func computeCloudBase(commitSHA, overrideVersion string) (string, error) {
	// The ancestry checks below cannot be answered truthfully in a shallow
	// clone; fail loudly instead.
	shallow, err := git.IsShallowRepository()
	if err != nil {
		return "", err
	}
	if shallow {
		return "", fmt.Errorf("this is a shallow clone, so cloud tag computation cannot check branch ancestry")
	}

	onMain, err := git.IsAncestor(commitSHA, "origin/main")
	if err != nil {
		return "", err
	}
	if !onMain {
		return "", fmt.Errorf("commit %s is not on origin/main; cloud releases are cut from main", commitSHA)
	}

	var base string
	if overrideVersion != "" {
		base = "v" + overrideVersion
	} else {
		branchVersion, err := FindTargetVersion(commitSHA)
		if err != nil {
			return "", fmt.Errorf("failed to detect the base version from release branches (pass --version to override): %w", err)
		}
		base = branchVersion.NextMinorBase()
		log.Infof("Newest release branch not containing %.10s: release/%s -> cloud base %s", commitSHA, branchVersion, base)
	}

	return base, nil
}
