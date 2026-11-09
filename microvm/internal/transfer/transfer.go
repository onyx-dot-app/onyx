// Package transfer runs the presigned object storage requests of the node
// agent (ENG-4572). The api_server signs each request for one object and
// one method; the agent sends it with exactly the signed headers and holds
// no storage credentials.
package transfer

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// Errors of this package. Test with errors.Is.
var (
	// ErrFailed: the request could not be sent, or got a non-2xx status.
	ErrFailed = errors.New("transfer failed")
	// ErrMismatch: the signed Content-Length or the response length is not
	// the expected size.
	ErrMismatch = errors.New("size mismatch")
	// ErrBadRequest: the presigned request is not valid (scheme, method).
	ErrBadRequest = errors.New("bad presigned request")
)

// Request is a presigned request.
type Request struct {
	URL     string
	Method  string
	Headers map[string]string
}

// Client sends presigned requests.
type Client struct {
	// HTTP is the client. Nil means a client with Timeout.
	HTTP *http.Client
	// Timeout bounds one whole request (body included). 0 means 10 min.
	Timeout time.Duration
	// AllowHTTP allows plain http URLs (a test MinIO). Default https only.
	AllowHTTP bool
}

func (c *Client) client() *http.Client {
	if c.HTTP != nil {
		return c.HTTP
	}
	return http.DefaultClient
}

func (c *Client) timeout() time.Duration {
	if c.Timeout > 0 {
		return c.Timeout
	}
	return 10 * time.Minute
}

// build checks r and makes the HTTP request. It never puts the URL in an
// error: the query string carries the signature.
func (c *Client) build(ctx context.Context, r Request, method string, body io.Reader) (*http.Request, error) {
	if !strings.EqualFold(r.Method, method) {
		return nil, fmt.Errorf("%w: method %q, want %s", ErrBadRequest, r.Method, method)
	}
	u, err := url.Parse(r.URL)
	if err != nil || u.Host == "" {
		return nil, fmt.Errorf("%w: the URL does not parse", ErrBadRequest)
	}
	switch {
	case u.Scheme == "https":
	case u.Scheme == "http" && c.AllowHTTP:
	default:
		return nil, fmt.Errorf("%w: scheme %q is not allowed", ErrBadRequest, u.Scheme)
	}
	req, err := http.NewRequestWithContext(ctx, method, u.String(), body)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrBadRequest, err)
	}
	for k, v := range r.Headers {
		switch http.CanonicalHeaderKey(k) {
		case "Content-Length":
			// Go sets it from ContentLength.
		case "Host":
			req.Host = v
		default:
			req.Header.Set(k, v)
		}
	}
	return req, nil
}

// Redacted returns the scheme, host and path of a presigned URL, for logs.
func Redacted(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return "<bad url>"
	}
	return u.Scheme + "://" + u.Host + u.Path
}

// PutResult is the answer to a PUT.
type PutResult struct {
	Status int
	ETag   string
}

// Put sends size bytes of body with a presigned PUT. If the signed headers
// have a Content-Length, it must be size.
func (c *Client) Put(ctx context.Context, r Request, body io.Reader, size int64) (PutResult, error) {
	for k, v := range r.Headers {
		if http.CanonicalHeaderKey(k) == "Content-Length" {
			n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64)
			if err != nil || n != size {
				return PutResult{}, fmt.Errorf("%w: signed Content-Length %q, the archive has %d bytes", ErrMismatch, v, size)
			}
		}
	}
	ctx, cancel := context.WithTimeout(ctx, c.timeout())
	defer cancel()
	req, err := c.build(ctx, r, http.MethodPut, body)
	if err != nil {
		return PutResult{}, err
	}
	req.ContentLength = size
	if size == 0 {
		req.Body = http.NoBody
	}
	resp, err := c.client().Do(req)
	if err != nil {
		return PutResult{}, fmt.Errorf("%w: PUT %s: %v", ErrFailed, Redacted(r.URL), unwrapURLErr(err))
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode/100 != 2 {
		return PutResult{Status: resp.StatusCode}, fmt.Errorf("%w: PUT %s: status %d: %s", ErrFailed, Redacted(r.URL),
			resp.StatusCode, snippet(resp.Body))
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	return PutResult{Status: resp.StatusCode, ETag: resp.Header.Get("ETag")}, nil
}

// Get opens a presigned GET. The caller reads and closes the body. If the
// response has a length, it must be size.
func (c *Client) Get(ctx context.Context, r Request, size int64) (io.ReadCloser, error) {
	ctx, cancel := context.WithTimeout(ctx, c.timeout())
	req, err := c.build(ctx, r, http.MethodGet, nil)
	if err != nil {
		cancel()
		return nil, err
	}
	resp, err := c.client().Do(req)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("%w: GET %s: %v", ErrFailed, Redacted(r.URL), unwrapURLErr(err))
	}
	if resp.StatusCode != http.StatusOK {
		msg := snippet(resp.Body)
		_ = resp.Body.Close()
		cancel()
		return nil, fmt.Errorf("%w: GET %s: status %d: %s", ErrFailed, Redacted(r.URL), resp.StatusCode, msg)
	}
	if resp.ContentLength >= 0 && resp.ContentLength != size {
		_ = resp.Body.Close()
		cancel()
		return nil, fmt.Errorf("%w: the object has %d bytes, want %d", ErrMismatch, resp.ContentLength, size)
	}
	return &cancelBody{ReadCloser: resp.Body, cancel: cancel}, nil
}

type cancelBody struct {
	io.ReadCloser
	cancel context.CancelFunc
}

func (b *cancelBody) Close() error {
	err := b.ReadCloser.Close()
	b.cancel()
	return err
}

// unwrapURLErr drops the *url.Error wrapper, whose text has the full URL.
func unwrapURLErr(err error) error {
	var ue *url.Error
	if errors.As(err, &ue) {
		return ue.Err
	}
	return err
}

func snippet(r io.Reader) string {
	b, _ := io.ReadAll(io.LimitReader(r, 512))
	return strings.TrimSpace(string(b))
}
