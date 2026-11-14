// Package nodewatch reads the agent's own Kubernetes Node and reports its
// drain taints. It reads the Node with the pod's service account
// (RBAC: get on nodes) and needs no Kubernetes client library. The same
// client reads the egress CA ConfigMap and annotates the Node
// (ScaleDownGuard).
package nodewatch

import (
	"bytes"
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
// kubectl cordon and kubectl drain set node.kubernetes.io/unschedulable;
// the cluster autoscaler sets ToBeDeletedByClusterAutoscaler before it
// removes a node, and does not cordon it.
var DefaultTaintKeys = []string{"node.kubernetes.io/unschedulable", "ToBeDeletedByClusterAutoscaler"}

// Taint is one Node taint.
type Taint struct {
	Key    string `json:"key"`
	Value  string `json:"value"`
	Effect string `json:"effect"`
}

func (t Taint) String() string { return t.Key + "=" + t.Value + ":" + t.Effect }

// Node is the part of a Node that the agent reads.
type Node struct {
	Taints      []Taint
	Annotations map[string]string
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

// InCluster reads the agent's Node, and ConfigMaps, from the Kubernetes API
// with the pod's service account.
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
	Metadata struct {
		Annotations map[string]string `json:"annotations"`
	} `json:"metadata"`
	Spec struct {
		Taints []Taint `json:"taints"`
	} `json:"spec"`
}

// Node implements Source.
func (c *InCluster) Node(ctx context.Context) (Node, error) {
	var n nodeJSON
	if err := c.get(ctx, "/api/v1/nodes/"+url.PathEscape(c.NodeName), "node "+c.NodeName, &n); err != nil {
		return Node{}, err
	}
	return Node{Taints: n.Spec.Taints, Annotations: n.Metadata.Annotations}, nil
}

// SetAnnotations sets the Node annotations in set and removes those whose
// value is nil, with one JSON merge patch (RBAC: patch on nodes).
func (c *InCluster) SetAnnotations(ctx context.Context, set map[string]*string) error {
	patch, err := json.Marshal(map[string]any{"metadata": map[string]any{"annotations": set}})
	if err != nil {
		return err
	}
	return c.do(ctx, http.MethodPatch, "/api/v1/nodes/"+url.PathEscape(c.NodeName), "node "+c.NodeName, patch, nil)
}

// ConfigMap returns the data of ConfigMap namespace/name (RBAC: get on that
// ConfigMap). The agent reads the egress CA with it.
func (c *InCluster) ConfigMap(ctx context.Context, namespace, name string) (map[string]string, error) {
	var cm struct {
		Data map[string]string `json:"data"`
	}
	path := "/api/v1/namespaces/" + url.PathEscape(namespace) + "/configmaps/" + url.PathEscape(name)
	if err := c.get(ctx, path, "configmap "+namespace+"/"+name, &cm); err != nil {
		return nil, err
	}
	return cm.Data, nil
}

// get reads one API object into out.
func (c *InCluster) get(ctx context.Context, path, what string, out any) error {
	return c.do(ctx, http.MethodGet, path, what, nil, out)
}

// do sends one API request; a body is a JSON merge patch. It reads the
// token on every call, because the kubelet rotates projected tokens. out
// may be nil.
func (c *InCluster) do(ctx context.Context, method, path, what string, body []byte, out any) error {
	tok, err := os.ReadFile(c.TokenPath)
	if err != nil {
		return fmt.Errorf("service account token: %w", err)
	}
	verb := strings.ToLower(method)
	var rd io.Reader
	if body != nil {
		rd = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, rd)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(tok)))
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/merge-patch+json")
	}
	resp, err := c.Client.Do(req)
	if err != nil {
		return fmt.Errorf("%s %s: %w", verb, what, err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return fmt.Errorf("%s %s: %w", verb, what, err)
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%s %s: HTTP %d: %s", verb, what, resp.StatusCode, strings.TrimSpace(string(raw[:min(len(raw), 300)])))
	}
	if out == nil {
		return nil
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return fmt.Errorf("%s %s: %w", verb, what, err)
	}
	return nil
}
