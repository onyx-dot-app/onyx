// Package client is a minimal hand-written HTTP client for the Onyx admin
// API, covering only the endpoints the Terraform provider manages. It mirrors
// the auth conventions of cli/internal/api (which cannot be imported here due
// to Go internal-package visibility).
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client talks to the Onyx backend API.
type Client struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client
}

// NewClient builds a client from the server origin (e.g. "http://localhost:3000"),
// an API prefix (usually "/api"; empty for direct backend access), and an
// admin-role API key or unrestricted PAT.
func NewClient(serverURL string, apiPrefix string, apiKey string) *Client {
	base := strings.TrimRight(serverURL, "/")
	if p := strings.Trim(apiPrefix, "/"); p != "" {
		base += "/" + p
	}
	return &Client{
		baseURL: base,
		apiKey:  apiKey,
		httpClient: &http.Client{
			Timeout: 3 * time.Minute,
		},
	}
}

// BaseURL returns the resolved API base URL (origin + prefix).
func (c *Client) BaseURL() string {
	return c.baseURL
}

func (c *Client) newRequest(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, body)
	if err != nil {
		return nil, err
	}
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
