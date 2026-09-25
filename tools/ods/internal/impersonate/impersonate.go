// Package impersonate mints, lists, and revokes session tokens on a single-tenant
// deployment by running an embedded Python payload inside the api-server pod.
//
// The payload imports nothing from onyx: customers run older images whose module
// paths differ from main. It uses the pod's env vars with redis and psycopg2, and
// writes a token that satisfies both session formats -- readers before July 2026
// take "sub" and ignore the rest, later ones parse issued_at/expires_at.
package impersonate

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/kube"
)

//go:embed impersonate.py
var embeddedScript string

// resultSentinel prefixes the payload's single result line, so onyx logging on
// stdout around it is ignored.
const resultSentinel = "__ONYX_IMPERSONATE_RESULT__"

// APIServerPod is the pod substring the payload runs on.
const APIServerPod = "api-server"

// Session is one entry in the pod's Redis session store.
type Session struct {
	Token          string `json:"token"`
	Sub            string `json:"sub"`
	Email          string `json:"email"`
	Status         string `json:"status"`
	TTLSeconds     int    `json:"ttl_seconds"`
	ExpiresAt      string `json:"expires_at"`
	ImpersonatedBy string `json:"impersonated_by"`
}

// Result is the payload's response. Only the fields for the request's command are set.
type Result struct {
	OK    bool   `json:"ok"`
	Error string `json:"error"`

	// mint
	Token     string `json:"token"`
	Email     string `json:"email"`
	UserID    string `json:"user_id"`
	Role      string `json:"role"`
	ExpiresAt string `json:"expires_at"`

	// list
	Sessions []Session `json:"sessions"`

	// revoke
	Deleted int      `json:"deleted"`
	Tokens  []string `json:"tokens"`
}

// run ships the payload to the pod and parses its sentinel line.
func run(c *kube.Cluster, pod string, request map[string]any) (*Result, error) {
	encoded, err := json.Marshal(request)
	if err != nil {
		return nil, fmt.Errorf("failed to encode request: %w", err)
	}

	stdout, err := c.ExecOnPodWithStdin(pod, embeddedScript, "python", "-", string(encoded))
	if err != nil {
		return nil, err
	}

	for _, line := range strings.Split(stdout, "\n") {
		if !strings.HasPrefix(line, resultSentinel) {
			continue
		}
		var result Result
		if err := json.Unmarshal([]byte(strings.TrimPrefix(line, resultSentinel)), &result); err != nil {
			return nil, fmt.Errorf("failed to decode result: %w", err)
		}
		if !result.OK {
			return nil, fmt.Errorf("%s", result.Error)
		}
		return &result, nil
	}

	return nil, fmt.Errorf("the api-server pod returned no result:\n%s", strings.TrimSpace(stdout))
}

// Mint writes a new session token for the given user and returns its cookie value.
func Mint(c *kube.Cluster, pod, email string, ttlSeconds int, operator string) (*Result, error) {
	return run(c, pod, map[string]any{
		"command":     "mint",
		"email":       email,
		"ttl_seconds": ttlSeconds,
		"operator":    operator,
	})
}

// List returns every session token currently in Redis.
func List(c *kube.Cluster, pod string) (*Result, error) {
	return run(c, pod, map[string]any{"command": "list"})
}

// Revoke deletes a single token, or every impersonation session for an email.
// Set includeRealSessions to also drop the user's own logins.
func Revoke(c *kube.Cluster, pod, email, token string, includeRealSessions bool) (*Result, error) {
	return run(c, pod, map[string]any{
		"command":               "revoke",
		"email":                 email,
		"token":                 token,
		"include_real_sessions": includeRealSessions,
	})
}
