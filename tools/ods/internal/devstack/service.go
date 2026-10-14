package devstack

import (
	"crypto/sha256"
	"encoding/hex"
	"sort"
	"strings"
	"time"
)

// Spec describes one application service to run.
type Spec struct {
	// Name is the launch configuration name, such as "API Server".
	Name string `json:"name"`
	// Slug is the short CLI name, such as "api".
	Slug string `json:"slug"`
	// Command is the program and its arguments.
	Command []string `json:"command"`
	// Dir is the working directory.
	Dir string `json:"dir"`
	// Env is the full environment, KEY=VALUE.
	Env []string `json:"-"`
	// Port is the host port the service listens on, 0 when it has none.
	Port int `json:"port,omitempty"`
	// Health is a URL that answers 200 once the service is ready.
	Health string `json:"health,omitempty"`
	// Optional services may exit without making the stack unready.
	Optional bool `json:"optional,omitempty"`
	// Skip, when set, is the reason the service is not started.
	Skip string `json:"skip,omitempty"`
}

// Hash identifies the spec so a reconcile can tell whether a running service
// still matches the plan. Secrets in Env never leave the hash.
func (sp Spec) Hash() string {
	h := sha256.New()
	write := func(parts ...string) {
		for _, p := range parts {
			h.Write([]byte(p))
			h.Write([]byte{0})
		}
	}
	write(sp.Name, sp.Slug, sp.Dir, sp.Health)
	write(sp.Command...)
	env := append([]string(nil), sp.Env...)
	sort.Strings(env)
	for _, entry := range env {
		key, _, _ := strings.Cut(entry, "=")
		if transientEnvironment(key) {
			continue
		}
		write(entry)
	}
	return hex.EncodeToString(h.Sum(nil))[:16]
}

func transientEnvironment(key string) bool {
	switch key {
	case "PWD", "OLDPWD", "SHLVL", "_", "TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "TERM_SESSION_ID", "SESSION_ID":
		return true
	}
	for _, prefix := range []string{"CODEX_", "CLAUDE_", "OMX_", "SC_", "SUPERCONDUCTOR_", "VSCODE_", "SSH_"} {
		if strings.HasPrefix(key, prefix) {
			return true
		}
	}
	return false
}

// ServiceRecord is a started (or skipped) service as persisted in State.
type ServiceRecord struct {
	Name        string         `json:"name"`
	Slug        string         `json:"slug"`
	Command     []string       `json:"command"`
	Dir         string         `json:"dir"`
	SpecHash    string         `json:"spec_hash"`
	Port        int            `json:"port,omitempty"`
	Health      string         `json:"health,omitempty"`
	Optional    bool           `json:"optional,omitempty"`
	Skipped     string         `json:"skipped,omitempty"`
	PID         int            `json:"pid,omitempty"`
	PGID        int            `json:"pgid,omitempty"`
	StartMarker string         `json:"start_marker,omitempty"`
	Members     map[int]string `json:"members,omitempty"`
	StartedAt   time.Time      `json:"started_at"`
	Log         string         `json:"log,omitempty"`
}

// Slugify turns a launch configuration name into a CLI service name.
func Slugify(name string) string {
	if slug, ok := knownSlugs[name]; ok {
		return slug
	}
	var b strings.Builder
	for _, r := range strings.ToLower(name) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9', r == '_', r == '-':
			b.WriteRune(r)
		case r == ' ':
			b.WriteRune('-')
		}
	}
	return strings.Trim(b.String(), "-")
}

var knownSlugs = map[string]string{
	"Web Server":   "web",
	"API Server":   "api",
	"MCP Server":   "mcp",
	"Model Server": "model",
	"Slack Bot":    "slack-bot",
	"Discord Bot":  "discord-bot",
}
