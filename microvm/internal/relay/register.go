package relay

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"
)

// SigningKeyPath is the api_server route that registers a node signing key
// (backend/onyx/server/features/microvm/api.py).
const SigningKeyPath = "/microvm/node/signing-key"

// KeyTTL is the cache TTL of a registered key on the api_server side.
const KeyTTL = time.Hour

// Registrar registers the node public key and keeps it alive.
type Registrar struct {
	// BaseURL is the api_server URL, without the route.
	BaseURL string
	// Secret is SANDBOX_NODE_REGISTRATION_SECRET.
	Secret string
	Signer *Signer
	// AgentAddress is the host:port of the agent's mTLS listener that the
	// api_server dials. Empty: not sent.
	AgentAddress string
	Client       *http.Client
	Log          *slog.Logger
	// Interval between successful registrations. Default KeyTTL/3.
	Interval time.Duration
	// Retry is the wait after a failure. Default 10 s.
	Retry time.Duration

	readyOnce, closeOnce sync.Once
	ready                chan struct{}
}

// Registered closes after the first successful registration.
func (g *Registrar) Registered() <-chan struct{} { return g.readyChan() }

func (g *Registrar) readyChan() chan struct{} {
	g.readyOnce.Do(func() { g.ready = make(chan struct{}) })
	return g.ready
}

func (g *Registrar) markRegistered() {
	ch := g.readyChan()
	g.closeOnce.Do(func() { close(ch) })
}

type registration struct {
	NodeID       string `json:"node_id"`
	KeyID        string `json:"key_id"`
	PublicKey    string `json:"public_key"`
	AgentAddress string `json:"agent_address,omitempty"`
}

// Register sends one registration.
func (g *Registrar) Register(ctx context.Context) error {
	body, err := json.Marshal(registration{
		NodeID: g.Signer.NodeID, KeyID: g.Signer.KeyID,
		PublicKey:    base64.StdEncoding.EncodeToString(g.Signer.PublicKey()),
		AgentAddress: g.AgentAddress,
	})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, strings.TrimRight(g.BaseURL, "/")+SigningKeyPath, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+g.Secret)
	c := g.Client
	if c == nil {
		c = &http.Client{Timeout: 15 * time.Second}
	}
	resp, err := c.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode/100 != 2 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("register signing key: HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	g.markRegistered()
	return nil
}

// Run registers at once and then again before the key TTL ends, until ctx ends.
func (g *Registrar) Run(ctx context.Context) {
	interval, retry := g.Interval, g.Retry
	if interval == 0 {
		interval = KeyTTL / 3
	}
	if retry == 0 {
		retry = 10 * time.Second
	}
	for {
		wait := interval
		if err := g.Register(ctx); err != nil {
			wait = retry
			g.Log.Error("node signing key registration failed", "key_id", g.Signer.KeyID, "err", err)
		} else {
			g.Log.Info("node signing key registered", "node_id", g.Signer.NodeID, "key_id", g.Signer.KeyID, "agent_address", g.AgentAddress)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}
