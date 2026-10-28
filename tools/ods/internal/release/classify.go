package release

import (
	"fmt"
	"regexp"
	"strings"
)

// Classification is the build-routing decision for a pushed tag: which images
// deployment.yml builds, and which Docker tags they receive.
type Classification struct {
	BuildDesktop     bool
	BuildWeb         bool
	BuildWebCloud    bool
	BuildBackend     bool
	BuildModelServer bool
	BuildSandbox     bool
	IsCloudTag       bool
	IsBeta           bool
	IsBetaStandalone bool
	IsStable         bool
	IsLatest         bool
	IsTestRun        bool
	SanitizedTag     string
	ShortSHA         string
}

// Routing patterns are deliberately looser than the policy regexes used by
// CheckTag. Routing describes what a pushed tag *is*, so an odd tag must still
// reach a sensible build; policy decides whether a tag should have been cut at
// all. classifyBetaRe therefore still accepts the legacy bare "-beta" form that
// betaTagRe rejects, and all three accept the leading zeroes that SemVer 2.0.0
// item 2 forbids.
var (
	// classifyVersionRe matches any tag that starts with a version, including
	// pre-release forms such as vX.Y.Z-beta.1 and vX.Y.Z-cloud.2.
	classifyVersionRe = regexp.MustCompile(`^v\d+\.\d+\.\d+`)
	// classifyStableRe matches a version tag with no pre-release suffix.
	classifyStableRe = regexp.MustCompile(`^v\d+\.\d+\.\d+$`)
	// classifyBetaRe matches a beta tag with or without a counter.
	classifyBetaRe = regexp.MustCompile(`^v\d+\.\d+\.\d+-beta(\.\d+)?$`)
)

// DevBuildTagPrefix marks an ad-hoc build of an unreleased commit. The
// release environment admits tags with this prefix so that their images
// publish under the tag name alone.
const DevBuildTagPrefix = "dev-build-"

// Classify routes a pushed tag to the images deployment.yml must build. ref is
// the tag name, sha the commit it points at, and event the triggering GitHub
// event ("push", "workflow_dispatch"). A workflow_dispatch on anything but a
// version or nightly tag is a test run.
func Classify(ref, sha, event string) (Classification, error) {
	// deployment.yml also gates jobs on these names with startsWith and ==,
	// which ignore case, so the matches here ignore case too.
	isDevBuild := hasPrefixFold(ref, DevBuildTagPrefix)
	// "cloud" is matched anywhere in the name, not just as a vX.Y.Z-cloud.N
	// suffix, so ad-hoc cloud tags still route to the cloud web image. A dev
	// build is never a cloud tag: a cloud tag dispatches the cloud deployment.
	isCloud := strings.Contains(ref, "cloud") && !isDevBuild
	isNightly := strings.HasPrefix(ref, "nightly")
	// Environments that deploy every image in one version (nightly, edge and
	// dev builds) need a sandbox image under that version too.
	isWholeStack := hasPrefixFold(ref, "nightly-latest") || strings.EqualFold(ref, "edge") || isDevBuild
	isVersion := classifyVersionRe.MatchString(ref)
	isStable := classifyStableRe.MatchString(ref)
	isBeta := classifyBetaRe.MatchString(ref)

	c := Classification{
		// The backend and model server ship for every tag.
		BuildBackend:     true,
		BuildModelServer: true,
		IsCloudTag:       isCloud,
		IsBeta:           isBeta,
		// The backend and model server treat a beta as a beta only when it is
		// not also a cloud tag.
		IsBetaStandalone: isBeta && !isCloud,
		IsStable:         isStable,
		// A workflow_dispatch on a non-production ref exercises the pipeline
		// without publishing a release.
		IsTestRun:    event == "workflow_dispatch" && !isVersion && !isNightly,
		SanitizedTag: strings.ReplaceAll(ref, "/", "-"),
		ShortSHA:     shortSHA(sha),
	}

	c.BuildSandbox = c.IsTestRun || isStable || isBeta || isCloud || isWholeStack

	if isCloud {
		c.BuildWebCloud = true
	} else {
		c.BuildWeb = true
		// The desktop app ships on stable and cloud-free pre-releases, but
		// never on a beta.
		c.BuildDesktop = isVersion && !isBeta
	}

	// Only the highest stable tag in the repository receives "latest".
	if isStable {
		highest, err := LatestStableTag()
		if err != nil {
			return Classification{}, fmt.Errorf("failed to determine the highest stable tag: %w", err)
		}
		c.IsLatest = ref == highest
	}

	return c, nil
}

// hasPrefixFold reports whether s begins with prefix, ignoring case.
func hasPrefixFold(s, prefix string) bool {
	return len(s) >= len(prefix) && strings.EqualFold(s[:len(prefix)], prefix)
}

// shortSHA truncates a commit SHA to the 7 characters used in image tags.
func shortSHA(sha string) string {
	if len(sha) > 7 {
		return sha[:7]
	}
	return sha
}

// GitHubOutput renders the classification as GITHUB_OUTPUT key=value lines.
// The keys are the step outputs deployment.yml jobs consume, so renaming one
// breaks the workflow.
func (c Classification) GitHubOutput() string {
	lines := []struct {
		key   string
		value string
	}{
		{"build-desktop", boolOutput(c.BuildDesktop)},
		{"build-web", boolOutput(c.BuildWeb)},
		{"build-web-cloud", boolOutput(c.BuildWebCloud)},
		{"build-backend", boolOutput(c.BuildBackend)},
		{"build-model-server", boolOutput(c.BuildModelServer)},
		{"build-sandbox", boolOutput(c.BuildSandbox)},
		{"is-cloud-tag", boolOutput(c.IsCloudTag)},
		{"is-beta", boolOutput(c.IsBeta)},
		{"is-beta-standalone", boolOutput(c.IsBetaStandalone)},
		{"is-stable", boolOutput(c.IsStable)},
		{"is-latest", boolOutput(c.IsLatest)},
		{"is-test-run", boolOutput(c.IsTestRun)},
		{"sanitized-tag", c.SanitizedTag},
		{"short-sha", c.ShortSHA},
	}

	var b strings.Builder
	for _, line := range lines {
		fmt.Fprintf(&b, "%s=%s\n", line.key, line.value)
	}
	return b.String()
}

// boolOutput renders a flag the way the workflow's `== 'true'` comparisons
// expect.
func boolOutput(v bool) string {
	if v {
		return "true"
	}
	return "false"
}
