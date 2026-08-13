// Package client is a minimal hand-written HTTP client for the Onyx admin
// API endpoints the Terraform provider manages.
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"
)

const (
	requestTimeout = 3 * time.Minute
	retryMax       = 4
	retryWaitMin   = 500 * time.Millisecond
	retryWaitMax   = 30 * time.Second
)

// Config holds everything NewClient needs to reach an Onyx deployment.
type Config struct {
	// ServerURL is the server origin, e.g. https://cloud.onyx.app.
	ServerURL string
	// APIPrefix is where the API is mounted: "/api" behind the web server,
	// empty when talking to the backend directly.
	APIPrefix string
	// APIKey is an admin API key or an unrestricted personal access token.
	APIKey string
	// Version of the provider, reported in the User-Agent header.
	Version string
}

// Client talks to the Onyx backend API.
type Client struct {
	baseURL    string
	apiKey     string
	userAgent  string
	retry      *retryablehttp.Client
	httpClient *http.Client
}

// NewClient builds a client that retries transient failures and identifies
// itself with a versioned User-Agent.
func NewClient(cfg Config) *Client {
	base := strings.TrimRight(cfg.ServerURL, "/")
	if p := strings.Trim(cfg.APIPrefix, "/"); p != "" {
		base += "/" + p
	}

	version := cfg.Version
	if version == "" {
		version = "dev"
	}

	retry := retryablehttp.NewClient()
	retry.HTTPClient = &http.Client{Timeout: requestTimeout}
	retry.RetryMax = retryMax
	retry.RetryWaitMin = retryWaitMin
	retry.RetryWaitMax = retryWaitMax
	retry.Logger = nil
	retry.CheckRetry = retryPolicy
	// Return the last response instead of a generic "giving up" error, so the
	// caller still reports the server's status code and body.
	retry.ErrorHandler = retryablehttp.PassthroughErrorHandler

	return &Client{
		baseURL:    base,
		apiKey:     cfg.APIKey,
		userAgent:  "terraform-provider-onyx/" + version,
		retry:      retry,
		httpClient: retry.StandardClient(),
	}
}

// BaseURL returns the resolved API base URL (origin + prefix).
func (c *Client) BaseURL() string {
	return c.baseURL
}

type replayableKey struct{}

// retryPolicy replays rate limits for every request, but replays transport
// errors and 5xx only when the request cannot have created something: a POST
// that timed out may already have been committed server-side.
func retryPolicy(ctx context.Context, resp *http.Response, err error) (bool, error) {
	if ctx.Err() != nil {
		return false, ctx.Err()
	}
	// A 429 is rejected before the handler runs, so replay is always safe.
	if resp != nil && resp.StatusCode == http.StatusTooManyRequests {
		return true, nil
	}
	if replayable, _ := ctx.Value(replayableKey{}).(bool); !replayable {
		return false, nil
	}
	return retryablehttp.DefaultRetryPolicy(ctx, resp, err)
}

func (c *Client) newRequest(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
	ctx = context.WithValue(ctx, replayableKey{}, method != http.MethodPost)
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", c.userAgent)
	if c.apiKey != "" {
		// X-Onyx-Authorization is checked first server-side and survives
		// proxies that consume the Authorization header.
		bearer := "Bearer " + c.apiKey
		req.Header.Set("Authorization", bearer)
		req.Header.Set("X-Onyx-Authorization", bearer)
	}
	return req, nil
}

// doJSON sends a JSON request and decodes the JSON response into result
// (skipped when result is nil). Non-2xx responses return an *APIError.
func (c *Client) doJSON(ctx context.Context, method, path string, reqBody any, result any) error {
	var body io.Reader
	if reqBody != nil {
		data, err := json.Marshal(reqBody)
		if err != nil {
			return err
		}
		body = bytes.NewReader(data)
	}

	req, err := c.newRequest(ctx, method, path, body)
	if err != nil {
		return err
	}
	if reqBody != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()

	if err := checkResponse(resp); err != nil {
		return err
	}

	if result != nil {
		return json.NewDecoder(resp.Body).Decode(result)
	}
	return nil
}
