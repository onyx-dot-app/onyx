package transfer

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPutSendsSignedHeaders(t *testing.T) {
	var got http.Header
	var host string
	var body string
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got, host = r.Header.Clone(), r.Host
		b, _ := io.ReadAll(r.Body)
		body = string(b)
		got.Set("X-Length", r.Header.Get("Content-Length"))
		w.Header().Set("ETag", `"e1"`)
	}))
	defer srv.Close()
	c := &Client{HTTP: srv.Client()}
	res, err := c.Put(context.Background(), Request{
		URL: srv.URL + "/b/k?X-Amz-Signature=secret", Method: "put",
		Headers: map[string]string{"Content-Length": "5", "x-amz-checksum-sha256": "abc", "Host": "bucket.example"},
	}, strings.NewReader("hello"), 5)
	if err != nil || res.Status != 200 || res.ETag != `"e1"` {
		t.Fatalf("put = %+v %v", res, err)
	}
	if body != "hello" || got.Get("X-Amz-Checksum-Sha256") != "abc" || got.Get("X-Length") != "5" || host != "bucket.example" {
		t.Fatalf("server saw %v host %q body %q", got, host, body)
	}
}

func TestRequestChecks(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "AccessDenied", http.StatusForbidden)
	}))
	defer srv.Close()
	ctx := context.Background()
	https := &Client{}
	if _, err := https.Put(ctx, Request{URL: srv.URL + "/x", Method: "PUT"}, strings.NewReader("a"), 1); !errors.Is(err, ErrBadRequest) {
		t.Fatalf("http url on an https-only client: %v", err)
	}
	if _, err := https.Get(ctx, Request{URL: "file:///etc/passwd", Method: "GET"}, 1); !errors.Is(err, ErrBadRequest) {
		t.Fatalf("file url: %v", err)
	}
	c := &Client{AllowHTTP: true}
	if _, err := c.Put(ctx, Request{URL: srv.URL + "/x", Method: "GET"}, strings.NewReader("a"), 1); !errors.Is(err, ErrBadRequest) {
		t.Fatalf("wrong method: %v", err)
	}
	_, err := c.Put(ctx, Request{URL: srv.URL + "/x", Method: "PUT", Headers: map[string]string{"content-length": "2"}},
		strings.NewReader("a"), 1)
	if !errors.Is(err, ErrMismatch) {
		t.Fatalf("signed length: %v", err)
	}
	_, err = c.Put(ctx, Request{URL: srv.URL + "/x?X-Amz-Signature=secret", Method: "PUT"}, strings.NewReader("a"), 1)
	if !errors.Is(err, ErrFailed) || !strings.Contains(err.Error(), "403") || strings.Contains(err.Error(), "secret") {
		t.Fatalf("403: %v", err)
	}
	if _, err := c.Get(ctx, Request{URL: srv.URL + "/x?X-Amz-Signature=secret", Method: "GET"}, 1); !errors.Is(err, ErrFailed) ||
		strings.Contains(err.Error(), "secret") {
		t.Fatalf("get 403: %v", err)
	}
	// A network error does not leak the signature either.
	_, err = c.Get(ctx, Request{URL: "http://127.0.0.1:1/x?X-Amz-Signature=secret", Method: "GET"}, 1)
	if !errors.Is(err, ErrFailed) || strings.Contains(err.Error(), "secret") {
		t.Fatalf("dial error: %v", err)
	}
}

func TestGetLength(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "abc")
	}))
	defer srv.Close()
	c := &Client{AllowHTTP: true}
	if _, err := c.Get(context.Background(), Request{URL: srv.URL, Method: "GET"}, 4); !errors.Is(err, ErrMismatch) {
		t.Fatalf("length: %v", err)
	}
	body, err := c.Get(context.Background(), Request{URL: srv.URL, Method: "GET"}, 3)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(body)
	_ = body.Close()
	if string(b) != "abc" {
		t.Fatalf("body %q", b)
	}
}
