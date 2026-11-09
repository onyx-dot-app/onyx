// Package relay is the egress relay: VM vsock → relay → sandbox-proxy.
//
// The relay reads one request head per connection, strips the VM's
// Proxy-Authorization and X-Onyx-Session-Hint, stamps a token signed with the
// node key (D1-A, verified by backend/onyx/sandbox_proxy/sandbox_identity/
// signed.py) and then streams both ways without buffering.
package relay

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"time"
)

// Audience is the token's aud claim: only sandbox-proxy accepts these tokens.
const Audience = "sandbox-proxy"

// TokenLifetime is the token lifetime. The proxy rejects more than 60 s.
const TokenLifetime = 60 * time.Second

var tenantRE = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// Subject returns the stable sandbox identity.
func Subject(tenantID, sandboxID string) (string, error) {
	if !tenantRE.MatchString(tenantID) {
		return "", fmt.Errorf("invalid tenant id %q", tenantID)
	}
	return "spiffe://onyx/tenant/" + tenantID + "/sandbox/" + sandboxID, nil
}

// NewKeyID returns a key ID for a new node key. The random suffix keeps two
// starts in the same second from reusing a key ID.
func NewKeyID(nodeID string, now time.Time) (string, error) {
	var b [4]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return nodeID + "-" + strconv.FormatInt(now.Unix(), 10) + "-" + hex.EncodeToString(b[:]), nil
}

// Signer signs identity tokens with the node key.
type Signer struct {
	NodeID string
	KeyID  string
	key    ed25519.PrivateKey
	now    func() time.Time
}

// NewSigner returns a Signer for the node key.
func NewSigner(nodeID, keyID string, key ed25519.PrivateKey) *Signer {
	return &Signer{NodeID: nodeID, KeyID: keyID, key: key, now: time.Now}
}

// PublicKey returns the raw 32-byte public key.
func (s *Signer) PublicKey() ed25519.PublicKey { return s.key.Public().(ed25519.PublicKey) }

type tokenHeader struct {
	Alg string `json:"alg"`
	Typ string `json:"typ"`
	Kid string `json:"kid"`
}

// Field order matches the shared test vectors.
type tokenClaims struct {
	Sub  string `json:"sub"`
	Gen  uint64 `json:"gen"`
	Node string `json:"node"`
	Iat  int64  `json:"iat"`
	Exp  int64  `json:"exp"`
	Jti  string `json:"jti"`
	Aud  string `json:"aud"`
}

// Token returns a fresh token for one connection of a VM.
func (s *Signer) Token(subject string, generation uint64) (string, error) {
	h, err := json.Marshal(tokenHeader{Alg: "EdDSA", Typ: "JWT", Kid: s.KeyID})
	if err != nil {
		return "", err
	}
	var jti [16]byte
	if _, err := rand.Read(jti[:]); err != nil {
		return "", err
	}
	now := s.now()
	c, err := json.Marshal(tokenClaims{
		Sub: subject, Gen: generation, Node: s.NodeID,
		Iat: now.Unix(), Exp: now.Add(TokenLifetime).Unix(), Jti: hex.EncodeToString(jti[:]), Aud: Audience,
	})
	if err != nil {
		return "", err
	}
	return s.SignRaw(h, c), nil
}

// SignRaw signs b64url(header).b64url(claims) as given, byte for byte.
func (s *Signer) SignRaw(headerJSON, claimsJSON []byte) string {
	enc := base64.RawURLEncoding
	input := enc.EncodeToString(headerJSON) + "." + enc.EncodeToString(claimsJSON)
	return input + "." + enc.EncodeToString(ed25519.Sign(s.key, []byte(input)))
}
