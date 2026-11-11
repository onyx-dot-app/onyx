// Package nodereport pushes the node's full VM state to the api_server.
//
// Each report has every VM of List and every VM instance that ended within
// --ended-retention. The api_server reconciles the node's placement records
// on each report (backend/onyx/microvm/node_report.py). This is E2B's
// 20 s sync with a push instead of a pull: Onyx has no API-side scheduler
// (microvm/README.md, "Sandbox state model"). The report is signed with the
// registered node key, so it starts only after the key registration succeeds.
package nodereport

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/relay"
)

// Path is the api_server route (backend/onyx/server/features/microvm/api.py).
const Path = "/microvm/node/state"

// Audience is the token's aud claim. It differs from relay.Audience, so a
// relay identity token is never a report token, and the reverse.
const Audience = "onyx-api-server-node-report"

// TokenLifetime is the token lifetime. The api_server rejects more than 60 s.
const TokenLifetime = 60 * time.Second

// MaxBodyBytes and MaxVMs match the api_server caps
// (NODE_REPORT_MAX_BODY_BYTES, NODE_REPORT_MAX_VMS). A larger report is not
// sent: a cut list would make the api_server clear live records.
const (
	MaxBodyBytes = 1 << 20
	MaxVMs       = 1024
	MaxEnded     = 1024
)

// DefaultInterval is the default --state-report-interval (E2B's sync interval).
const DefaultInterval = 20 * time.Second

// DefaultMaxBackoff caps the wait after repeated failures.
const DefaultMaxBackoff = 2 * time.Minute

// VM is one VM of the agent's List.
type VM struct {
	SandboxID  string     `json:"sandbox_id"`
	TenantID   string     `json:"tenant_id"`
	Attempt    uint64     `json:"attempt"`
	Generation uint64     `json:"generation"`
	State      string     `json:"state"`
	Template   string     `json:"template"`
	VCPUs      uint32     `json:"vcpus"`
	MemMiB     uint32     `json:"mem_mib"`
	ScratchGiB uint32     `json:"scratch_gib"`
	PID        int        `json:"pid"`
	StartedAt  *time.Time `json:"started_at"`
}

// EndedVM is one VM instance that exited or stopped within --ended-retention.
type EndedVM struct {
	SandboxID  string    `json:"sandbox_id"`
	TenantID   string    `json:"tenant_id"`
	Attempt    uint64    `json:"attempt"`
	Generation uint64    `json:"generation"`
	Reason     string    `json:"reason"`
	EndedAt    time.Time `json:"ended_at"`
}

type report struct {
	NodeID string    `json:"node_id"`
	VMs    []VM      `json:"vms"`
	Ended  []EndedVM `json:"ended"`
}

type tokenHeader struct {
	Alg string `json:"alg"`
	Typ string `json:"typ"`
	Kid string `json:"kid"`
}

type tokenClaims struct {
	Node       string `json:"node"`
	Iat        int64  `json:"iat"`
	Exp        int64  `json:"exp"`
	Jti        string `json:"jti"`
	Aud        string `json:"aud"`
	BodySHA256 string `json:"body_sha256"`
}

// Reporter sends the VM list on start and then every Interval.
type Reporter struct {
	// BaseURL is the api_server URL, without the route (--api-server-url).
	BaseURL string
	// Signer holds the registered node key; its KeyID is the token kid.
	Signer *relay.Signer
	// List returns the node's VMs.
	List func() []VM
	// Ended returns the VM instances that ended recently. nil: none.
	Ended func() []EndedVM
	// Ready closes when the key registration first succeeds.
	Ready  <-chan struct{}
	Client *http.Client
	Log    *slog.Logger
	// Interval between reports. Must be more than 0.
	Interval time.Duration
	// MaxBackoff caps the wait after failures. Default DefaultMaxBackoff.
	MaxBackoff time.Duration
	// Now is the token clock. Default time.Now.
	Now func() time.Time
}

// Body returns the JSON report of vms and ended, or an error if it is over
// the caps. Only the oldest ended entries are dropped over MaxEnded: a lost
// ended entry delays a record clear, it never clears a live record.
func Body(nodeID string, vms []VM, ended []EndedVM) ([]byte, error) {
	if len(vms) > MaxVMs {
		return nil, fmt.Errorf("node report has %d VMs, the cap is %d", len(vms), MaxVMs)
	}
	if vms == nil {
		vms = []VM{}
	}
	if len(ended) > MaxEnded {
		ended = ended[len(ended)-MaxEnded:]
	}
	if ended == nil {
		ended = []EndedVM{}
	}
	body, err := json.Marshal(report{NodeID: nodeID, VMs: vms, Ended: ended})
	if err != nil {
		return nil, err
	}
	if len(body) > MaxBodyBytes {
		return nil, fmt.Errorf("node report is %d bytes, the cap is %d", len(body), MaxBodyBytes)
	}
	return body, nil
}

// Token returns the report token for body.
func (r *Reporter) Token(body []byte) (string, error) {
	h, err := json.Marshal(tokenHeader{Alg: "EdDSA", Typ: "JWT", Kid: r.Signer.KeyID})
	if err != nil {
		return "", err
	}
	var jti [16]byte
	if _, err := rand.Read(jti[:]); err != nil {
		return "", err
	}
	now := r.now()
	sum := sha256.Sum256(body)
	c, err := json.Marshal(tokenClaims{
		Node: r.Signer.NodeID, Iat: now.Unix(), Exp: now.Add(TokenLifetime).Unix(),
		Jti: hex.EncodeToString(jti[:]), Aud: Audience, BodySHA256: hex.EncodeToString(sum[:]),
	})
	if err != nil {
		return "", err
	}
	return r.Signer.SignRaw(h, c), nil
}

func (r *Reporter) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

// Send sends one report.
func (r *Reporter) Send(ctx context.Context) error {
	var ended []EndedVM
	if r.Ended != nil {
		ended = r.Ended()
	}
	body, err := Body(r.Signer.NodeID, r.List(), ended)
	if err != nil {
		return err
	}
	token, err := r.Token(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(r.BaseURL, "/")+Path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	c := r.Client
	if c == nil {
		// Above the api_server's 20 s pass deadline.
		c = &http.Client{Timeout: 30 * time.Second}
	}
	resp, err := c.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode/100 != 2 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("node state report: HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))
	return nil
}

// Backoff is the wait after `failures` failures in a row: the interval,
// doubled per failure, at most max(maxBackoff, interval).
func Backoff(interval, maxBackoff time.Duration, failures int) time.Duration {
	maxBackoff = max(maxBackoff, interval)
	wait := interval
	for i := 0; i < failures && wait < maxBackoff; i++ {
		wait *= 2
	}
	return min(wait, maxBackoff)
}

// send is Send, with a panic turned into an error: a report never stops
// the agent.
func (r *Reporter) send(ctx context.Context) (err error) {
	defer func() {
		if p := recover(); p != nil {
			err = fmt.Errorf("node state report panicked: %v", p)
		}
	}()
	return r.Send(ctx)
}

// Run waits for Ready, reports at once and then every Interval, until ctx
// ends. A failure is logged and the next report waits longer (Backoff).
func (r *Reporter) Run(ctx context.Context) {
	maxBackoff := r.MaxBackoff
	if maxBackoff <= 0 {
		maxBackoff = DefaultMaxBackoff
	}
	select {
	case <-ctx.Done():
		return
	case <-r.Ready:
	}
	timer := time.NewTimer(0)
	defer timer.Stop()
	failures := 0
	for {
		select {
		case <-ctx.Done():
			return
		case <-timer.C:
		}
		if err := r.send(ctx); err != nil {
			if ctx.Err() != nil {
				return
			}
			failures++
			r.Log.Error("node state report failed", "node_id", r.Signer.NodeID, "failures", failures, "err", err)
		} else {
			if failures > 0 {
				r.Log.Info("node state report sent again", "node_id", r.Signer.NodeID, "after_failures", failures)
			}
			failures = 0
		}
		timer.Reset(Backoff(r.Interval, maxBackoff, failures))
	}
}
