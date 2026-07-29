// Package release resolves Onyx app release tags and fetches deployment files
// for a pinned ref from GitHub, so a deployment can match versions other than
// the snapshot embedded in this binary.
package release

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

const (
	defaultAPIBase = "https://api.github.com"
	defaultRawBase = "https://raw.githubusercontent.com"
	owner          = "onyx-dot-app"
	repo           = "onyx"

	// fetchAttempts bounds retries for raw-file downloads (mirrors
	// install.sh's `curl --retry`).
	fetchAttempts     = 3
	defaultRetryDelay = 2 * time.Second
)

// appTagPattern matches Onyx app release tags (vX.Y.Z, optionally suffixed
// like v4.4.6-beta.1), as opposed to tool releases such as cli/v1.2.3.
var appTagPattern = regexp.MustCompile(`^v\d+\.\d+\.\d+`)

// refPattern bounds what may be interpolated into a raw.githubusercontent
// URL path. The ref comes from user input (--tag), and the files it selects
// are written to the install root and executed by the deployment, so a ref
// that could escape the repo (".." segments) must never reach the network.
var refPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._/-]*$`)

func checkRef(ref string) error {
	if !refPattern.MatchString(ref) || strings.Contains(ref, "..") {
		return fmt.Errorf("invalid git ref %q", ref)
	}
	return nil
}

// releaseVersionPattern matches a release version as a user would type it,
// with or without the conventional "v" prefix. Image tags that are not git
// refs (beta, nightly, vX.Y.Z-dev, locally built tags) deliberately don't
// match: they are pullable but can't be looked up in the repo.
var releaseVersionPattern = regexp.MustCompile(`^v?\d+\.\d+\.\d+$`)

// NormalizeVersionTag adds the conventional "v" prefix to a bare release
// version ("4.4.6" → "v4.4.6") and reports whether the result is a release
// version, i.e. one whose existence can be checked with RefExists.
func NormalizeVersionTag(tag string) (string, bool) {
	if !releaseVersionPattern.MatchString(tag) {
		return tag, false
	}
	if !strings.HasPrefix(tag, "v") {
		return "v" + tag, true
	}
	return tag, true
}

// FloatingTags are rolling image tags that track main rather than a pinned
// release.
func IsFloatingTag(tag string) bool {
	return tag == "edge" || tag == "latest"
}

// IsImmutableTag reports whether tag names images that are published once and
// never re-pushed, so a copy already on the host is the copy this deployment
// wants. Only released versions qualify: floating tags move by design, and the
// -dev twins are rebuilt per commit under the same name.
func IsImmutableTag(tag string) bool {
	rest, ok := strings.CutPrefix(tag, "v")
	if !ok {
		return false
	}
	parts := strings.Split(rest, ".")
	if len(parts) != 3 {
		return false
	}
	for _, p := range parts {
		if p == "" || strings.TrimLeft(p, "0123456789") != "" {
			return false
		}
	}
	return true
}

// ConfigRef maps an image tag to the git ref its deployment files ship at:
// floating tags track main, pinned tags use their own ref (mirrors
// install.sh's CONFIG_REF logic).
func ConfigRef(tag string) string {
	if IsFloatingTag(tag) {
		return "main"
	}
	return tag
}

// Client talks to GitHub. The zero-ish defaults from NewClient hit the real
// API; tests point APIBase/RawBase at httptest servers.
type Client struct {
	HTTP    *http.Client
	APIBase string
	RawBase string
	// RetryDelay is the pause between fetch attempts (defaults to 2s).
	RetryDelay time.Duration
}

// NewClient returns a client with conservative timeouts: release lookup and
// file fetches gate interactive install steps, so failing fast (callers fall
// back to main/edge or embedded files) beats hanging.
func NewClient() *Client {
	return &Client{
		HTTP:       &http.Client{Timeout: 10 * time.Second},
		APIBase:    defaultAPIBase,
		RawBase:    defaultRawBase,
		RetryDelay: defaultRetryDelay,
	}
}

type releaseInfo struct {
	TagName    string `json:"tag_name"`
	Draft      bool   `json:"draft"`
	Prerelease bool   `json:"prerelease"`
}

// LatestAppTag returns the newest Onyx app release tag (vX.Y.Z).
//
// /releases/latest is repo-global: this repo also publishes desktop and tool
// releases (cli/v*, ods/v*) under the same namespace, so the result is
// verified against appTagPattern and, when it doesn't match, the release list
// is scanned for the newest app tag instead. install.sh trusts
// /releases/latest blindly; this hardening keeps the default deploy tag an
// app version even if another release family is ever marked latest.
func (c *Client) LatestAppTag(ctx context.Context) (string, error) {
	var latest releaseInfo
	if err := c.getJSON(ctx, c.APIBase+"/repos/"+owner+"/"+repo+"/releases/latest", &latest); err == nil {
		if appTagPattern.MatchString(latest.TagName) {
			return latest.TagName, nil
		}
	}

	var releases []releaseInfo
	if err := c.getJSON(ctx, c.APIBase+"/repos/"+owner+"/"+repo+"/releases?per_page=100", &releases); err != nil {
		return "", fmt.Errorf("failed to look up the latest Onyx release: %w", err)
	}
	for _, r := range releases {
		if r.Draft || r.Prerelease {
			continue
		}
		if appTagPattern.MatchString(r.TagName) {
			return r.TagName, nil
		}
	}
	return "", fmt.Errorf("no Onyx app release found among the repository's releases")
}

// ErrNotFound reports that the ref is reachable but doesn't carry the file.
// Callers distinguish it from a transport failure: one means this deployment
// simply didn't ship that file at that version, the other means the network
// is unusable and nothing more should be fetched.
var ErrNotFound = errors.New("not found")

// FetchFile downloads repoPath (e.g. "deployment/docker_compose/env.template")
// at ref. A 404 fails immediately (the ref or path doesn't exist); transient
// errors are retried. Callers fall back to the embedded copies on error.
func (c *Client) FetchFile(ctx context.Context, ref, repoPath string) ([]byte, error) {
	if err := checkRef(ref); err != nil {
		return nil, err
	}
	url := c.RawBase + "/" + owner + "/" + repo + "/" + ref + "/" + repoPath

	var lastErr error
	for attempt := 0; attempt < fetchAttempts; attempt++ {
		if attempt > 0 {
			delay := c.RetryDelay
			if delay == 0 {
				delay = defaultRetryDelay
			}
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(delay):
			}
		}
		data, retryable, err := c.fetchOnce(ctx, url)
		if err == nil {
			return data, nil
		}
		lastErr = err
		if !retryable {
			break
		}
	}
	return nil, fmt.Errorf("failed to fetch %s at %s: %w", repoPath, ref, lastErr)
}

// RefExists reports whether ref (a tag or branch) exists in the repo, via a
// HEAD request for a file present at every deployable ref. A definitive 404
// means the ref doesn't exist; transport errors and other statuses return an
// error so callers can decide whether to proceed unverified.
func (c *Client) RefExists(ctx context.Context, ref string) (bool, error) {
	if err := checkRef(ref); err != nil {
		return false, err
	}
	url := c.RawBase + "/" + owner + "/" + repo + "/" + ref + "/deployment/docker_compose/env.template"
	req, err := http.NewRequestWithContext(ctx, http.MethodHead, url, nil)
	if err != nil {
		return false, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return false, err
	}
	defer func() { _ = resp.Body.Close() }()
	switch resp.StatusCode {
	case http.StatusOK:
		return true, nil
	case http.StatusNotFound:
		return false, nil
	default:
		return false, fmt.Errorf("HTTP %d checking ref %s", resp.StatusCode, ref)
	}
}

func (c *Client) fetchOnce(ctx context.Context, url string) (data []byte, retryable bool, err error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, false, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, true, err
	}
	defer func() { _ = resp.Body.Close() }()

	switch {
	case resp.StatusCode == http.StatusOK:
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return nil, true, err
		}
		return body, false, nil
	case resp.StatusCode == http.StatusNotFound:
		return nil, false, fmt.Errorf("%w (HTTP 404)", ErrNotFound)
	case resp.StatusCode >= 500:
		return nil, true, fmt.Errorf("HTTP %d", resp.StatusCode)
	default:
		return nil, false, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
}

func (c *Client) getJSON(ctx context.Context, url string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d from %s", resp.StatusCode, url)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}
