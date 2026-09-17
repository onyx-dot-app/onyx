package release

import (
	"fmt"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

// FetchTags force-updates the local tags matching pattern from origin. A
// fetch refspec allows only one wildcard per side, so the matching tag names
// are listed with ls-remote (which globs freely) and fetched by exact refspec.
func FetchTags(pattern string) error {
	out, err := exec.Command("git", "ls-remote", "--tags", "origin", pattern).Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && len(exitErr.Stderr) > 0 {
			return fmt.Errorf("git ls-remote failed: %w: %s", err, strings.TrimSpace(string(exitErr.Stderr)))
		}
		return fmt.Errorf("git ls-remote failed: %w", err)
	}

	refspecs := []string{}
	for _, line := range strings.Split(string(out), "\n") {
		// Each line is "<sha>\trefs/tags/<name>".
		_, ref, found := strings.Cut(line, "\t")
		if !found {
			continue
		}
		ref = strings.TrimSpace(ref)
		// Annotated tags list a second, peeled "<ref>^{}" entry; the plain ref
		// covers it.
		if strings.HasSuffix(ref, "^{}") {
			continue
		}
		refspecs = append(refspecs, fmt.Sprintf("+%s:%s", ref, ref))
	}
	if len(refspecs) == 0 {
		return nil
	}

	args := append([]string{"fetch", "--quiet", "origin"}, refspecs...)
	return git.RunCommand(args...)
}

// tagExists reports whether the tag exists locally (fetched from origin
// beforehand).
func tagExists(tag string) bool {
	return exec.Command("git", "rev-parse", "-q", "--verify", "refs/tags/"+tag).Run() == nil
}

// nextSequencedTag returns prefix + N where N is one past the highest
// existing counter among local tags named prefix + <integer> (fetched from
// origin beforehand), or 0 when none exist. Counters compare numerically:
// lexically ".9" > ".10", which would compute a colliding tag. Tags of other
// prefixes and tags whose suffix is not a plain integer (including
// leading-zero counters, rejected per SemVer 2.0.0 item 2) are ignored, as is
// excludeTag (which lets a check recompute the sequence as if the checked tag
// did not exist).
func nextSequencedTag(prefix, excludeTag string) (string, error) {
	out, err := exec.Command("git", "tag", "--list", prefix+"*").Output()
	if err != nil {
		return "", fmt.Errorf("git tag --list failed: %w", err)
	}
	counterRe := regexp.MustCompile(`^` + regexp.QuoteMeta(prefix) + `(0|[1-9]\d*)$`)
	next := 0
	for _, line := range strings.Split(string(out), "\n") {
		tag := strings.TrimSpace(line)
		if tag == excludeTag {
			continue
		}
		matches := counterRe.FindStringSubmatch(tag)
		if matches == nil {
			continue
		}
		n, err := strconv.Atoi(matches[1])
		if err != nil {
			continue
		}
		if n >= next {
			next = n + 1
		}
	}
	return fmt.Sprintf("%s%d", prefix, next), nil
}

// LatestStableTag returns the highest stable tag (vX.Y.Z, no pre-release
// suffix) among the local tags, or "" when the repository has none. Tags are
// ordered numerically on major, then minor, then patch; pre-release tags such
// as vX.Y.Z-beta.N and vX.Y.Z-cloud.N are ignored.
func LatestStableTag() (string, error) {
	out, err := exec.Command("git", "tag", "--list", "v*").Output()
	if err != nil {
		return "", fmt.Errorf("git tag --list failed: %w", err)
	}

	latestTag := ""
	latest := [3]int{}
	for _, line := range strings.Split(string(out), "\n") {
		tag := strings.TrimSpace(line)
		version, ok := parseStableTag(tag)
		if !ok {
			continue
		}
		if latestTag == "" || version[0] > latest[0] ||
			version[0] == latest[0] && (version[1] > latest[1] ||
				version[1] == latest[1] && version[2] > latest[2]) {
			latestTag, latest = tag, version
		}
	}
	return latestTag, nil
}

// parseStableTag splits a stable tag into its numeric major, minor, and patch
// components. It reports false for any tag that is not a bare vX.Y.Z.
func parseStableTag(tag string) ([3]int, bool) {
	version := [3]int{}
	matches := stableTagRe.FindStringSubmatch(tag)
	if matches == nil {
		return version, false
	}
	major, minor, found := strings.Cut(matches[1], ".")
	if !found {
		return version, false
	}
	for i, part := range [3]string{major, minor, matches[2]} {
		n, err := strconv.Atoi(part)
		if err != nil {
			return version, false
		}
		version[i] = n
	}
	return version, true
}
