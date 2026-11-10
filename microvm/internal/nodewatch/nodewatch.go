// Package nodewatch reads the agent's own Kubernetes Node and reports its
// drain taints (ENG-4569). It reads the Node with the pod's service account
// (RBAC: get on nodes) and needs no Kubernetes client library.
package nodewatch

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"slices"
	"strings"
	"time"
)

// DefaultTaintKeys are the taint keys that drain the node by default:
// kubectl cordon and kubectl drain set node.kubernetes.io/unschedulable.
var DefaultTaintKeys = []string{"node.kubernetes.io/unschedulable"}

// Taint is one Node taint.
type Taint struct {
	Key    string `json:"key"`
	Value  string `json:"value"`
	Effect string `json:"effect"`
}

func (t Taint) String() string { return t.Key + "=" + t.Value + ":" + t.Effect }

// Node is the part of a Node that the agent reads.
type Node struct {
	Taints []Taint
}

// Source reads the Node.
type Source interface {
	Node(ctx context.Context) (Node, error)
}

// DrainTaints returns the taints of n whose key is in keys, as
// "key=value:effect", sorted.
func DrainTaints(n Node, keys []string) []string {
	var out []string
	for _, t := range n.Taints {
		if slices.Contains(keys, t.Key) {
			out = append(out, t.String())
		}
	}
	slices.Sort(out)
	return slices.Compact(out)
}

// Watcher reads the Node every Interval and passes the drain taints, or the
// read error, to Apply.
type Watcher struct {
	Source   Source
	Keys     []string
	Interval time.Duration
	// Timeout bounds one read. 0 means Interval.
	Timeout time.Duration
	Apply   func(taints []string, err error)
}

// Once reads the Node one time and calls Apply.
func (w *Watcher) Once(ctx context.Context) {
	timeout := w.Timeout
	if timeout <= 0 {
		timeout = w.Interval
	}
	rctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	n, err := w.Source.Node(rctx)
	if err != nil {
		w.Apply(nil, err)
		return
	}
	w.Apply(DrainTaints(n, w.Keys), nil)
}

// Run reads the Node at once and then every Interval until ctx ends.
func (w *Watcher) Run(ctx context.Context) {
	t := time.NewTicker(w.Interval)
	defer t.Stop()
	for {
		w.Once(ctx)
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}

// Service account files of a pod.
const (
	TokenPath = "/var/run/secrets/kubernetes.io/serviceaccount/token"
	CAPath    = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
)

// InCluster reads one Node from the Kubernetes API with the pod's service
// account.
type InCluster struct {
	// BaseURL is the API server, for example https://10.0.0.1:443.
	BaseURL   string
	NodeName  string
	TokenPath string
	Client    *http.Client
}

// NewInCluster returns an InCluster for nodeName from the pod environment
// (KUBERNETES_SERVICE_HOST, KUBERNETES_SERVICE_PORT and the service account
// files).
func NewInCluster(nodeName string) (*InCluster, error) {
	if nodeName == "" {
		return nil, errors.New("no node name")
	}
	host, port := os.Getenv("KUBERNETES_SERVICE_HOST"), os.Getenv("KUBERNETES_SERVICE_PORT")
	if host == "" || port == "" {
		return nil, errors.New("not in a Kubernetes pod: KUBERNETES_SERVICE_HOST or KUBERNETES_SERVICE_PORT is not set")
	}
	caPEM, err := os.ReadFile(CAPath)
	if err != nil {
		return nil, fmt.Errorf("service account CA: %w", err)
	}
	if _, err := os.Stat(TokenPath); err != nil {
		return nil, fmt.Errorf("service account token: %w", err)
	}
	return NewWithCA("https://"+net.JoinHostPort(host, port), nodeName, TokenPath, caPEM)
}

// NewWithCA returns an InCluster that trusts caPEM.
func NewWithCA(baseURL, nodeName, tokenPath string, caPEM []byte) (*InCluster, error) {
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, errors.New("no certificate in the CA file")
	}
	return &InCluster{
		BaseURL: baseURL, NodeName: nodeName, TokenPath: tokenPath,
		Client: &http.Client{Transport: &http.Transport{
			TLSClientConfig: &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12},
			Proxy:           nil,
		}},
	}, nil
}

type nodeJSON struct {
	Spec struct {
		Taints []Taint `json:"taints"`
	} `json:"spec"`
}

// Node implements Source. It reads the token on every call, because the
// kubelet rotates projected tokens.
func (c *InCluster) Node(ctx context.Context) (Node, error) {
	tok, err := os.ReadFile(c.TokenPath)
	if err != nil {
		return Node{}, fmt.Errorf("service account token: %w", err)
	}
	u := c.BaseURL + "/api/v1/nodes/" + url.PathEscape(c.NodeName)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return Node{}, err
	}
	req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(tok)))
	req.Header.Set("Accept", "application/json")
	resp, err := c.Client.Do(req)
	if err != nil {
		return Node{}, fmt.Errorf("get node %s: %w", c.NodeName, err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return Node{}, fmt.Errorf("get node %s: %w", c.NodeName, err)
	}
	if resp.StatusCode != http.StatusOK {
		return Node{}, fmt.Errorf("get node %s: HTTP %d: %s", c.NodeName, resp.StatusCode, strings.TrimSpace(string(body[:min(len(body), 300)])))
	}
	var n nodeJSON
	if err := json.Unmarshal(body, &n); err != nil {
		return Node{}, fmt.Errorf("get node %s: %w", c.NodeName, err)
	}
	return Node{Taints: n.Spec.Taints}, nil
}
