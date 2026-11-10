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
	// Timeout bounds one whole request (body included), or one whole ranged
	// download (all parts). 0 means 10 min.
	Timeout time.Duration
	// AllowHTTP allows plain http URLs (a test MinIO). Default https only.
	AllowHTTP bool
	// Parallel is the number of range GETs that Get runs at once for an
	// object larger than PartBytes. 0 or 1 means one plain GET. One S3
	// stream gives about 100 MB/s; 8 ranges about 450 MB/s.
	Parallel int
	// PartBytes is the size of one range. 0 means 8 MiB. Get holds at most
	// Parallel + 1 parts in memory.
	PartBytes int64
}

// client returns a copy of the HTTP client that also checks the scheme of
// every redirect, so an https request is never sent on over http.
func (c *Client) client() *http.Client {
	base := c.HTTP
	if base == nil {
		base = http.DefaultClient
	}
	hc := *base
	next := base.CheckRedirect
	hc.CheckRedirect = func(req *http.Request, via []*http.Request) error {
		if err := c.checkScheme(req.URL); err != nil {
			return err
		}
		if next != nil {
			return next(req, via)
		}
		if len(via) >= 10 {
			return errors.New("stopped after 10 redirects")
		}
		return nil
	}
	return &hc
}

func (c *Client) checkScheme(u *url.URL) error {
	switch {
	case u.Scheme == "https":
	case u.Scheme == "http" && c.AllowHTTP:
	default:
		return fmt.Errorf("%w: scheme %q is not allowed", ErrBadRequest, u.Scheme)
	}
	return nil
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
	if err := c.checkScheme(u); err != nil {
		return nil, err
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
		return PutResult{}, fmt.Errorf("%w: PUT %s: %w", ErrFailed, Redacted(r.URL), unwrapURLErr(err))
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode/100 != 2 {
		return PutResult{Status: resp.StatusCode}, fmt.Errorf("%w: PUT %s: status %d: %s", ErrFailed, Redacted(r.URL),
			resp.StatusCode, snippet(resp.Body))
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	return PutResult{Status: resp.StatusCode, ETag: resp.Header.Get("ETag")}, nil
}

// Get opens a presigned GET of an object of size bytes. The caller reads
// and closes the body. With Parallel > 1 it reads the object in ranges at
// once and returns the bytes in order.
func (c *Client) Get(ctx context.Context, r Request, size int64) (io.ReadCloser, error) {
	part := c.PartBytes
	if part <= 0 {
		part = 8 << 20
	}
	if c.Parallel > 1 && size > part {
		if _, err := c.build(ctx, r, http.MethodGet, nil); err != nil {
			return nil, err
		}
		return c.getRanges(ctx, r, size, part), nil
	}
	return c.getOne(ctx, r, size)
}

// getOne is one plain GET. If the response has a length, it must be size.
func (c *Client) getOne(ctx context.Context, r Request, size int64) (io.ReadCloser, error) {
	ctx, cancel := context.WithTimeout(ctx, c.timeout())
	req, err := c.build(ctx, r, http.MethodGet, nil)
	if err != nil {
		cancel()
		return nil, err
	}
	resp, err := c.client().Do(req)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("%w: GET %s: %w", ErrFailed, Redacted(r.URL), unwrapURLErr(err))
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

// rangeReader returns the parts of a ranged download in order.
type rangeReader struct {
	ctx    context.Context
	cancel context.CancelFunc
	parts  []chan partResult
	slots  chan struct{}
	next   int
	cur    []byte
	err    error
}

type partResult struct {
	data []byte
	err  error
}

// getRanges starts the range GETs. A worker takes a slot before it fetches
// a part, and the reader frees the slot when it takes the part, so at most
// Parallel parts wait in memory.
func (c *Client) getRanges(ctx context.Context, r Request, size, part int64) io.ReadCloser {
	ctx, cancel := context.WithTimeout(ctx, c.timeout())
	n := int((size + part - 1) / part)
	rr := &rangeReader{ctx: ctx, cancel: cancel, parts: make([]chan partResult, n), slots: make(chan struct{}, c.Parallel)}
	for i := range rr.parts {
		rr.parts[i] = make(chan partResult, 1)
	}
	go func() {
		for i := 0; i < n; i++ {
			select {
			case rr.slots <- struct{}{}:
			case <-ctx.Done():
				return
			}
			from := int64(i) * part
			to := min(from+part, size) - 1
			go func(i int) {
				sr := sizedRequest{Request: r, size: size}
				data, err := c.getRange(ctx, sr, from, to)
				if err != nil && !errors.Is(err, ErrMismatch) && ctx.Err() == nil {
					// One retry: a single slow or reset connection is common.
					data, err = c.getRange(ctx, sr, from, to)
				}
				rr.parts[i] <- partResult{data: data, err: err}
			}(i)
		}
	}()
	return rr
}

type sizedRequest struct {
	Request
	size int64
}

func (c *Client) getRange(ctx context.Context, r sizedRequest, from, to int64) ([]byte, error) {
	req, err := c.build(ctx, r.Request, http.MethodGet, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", from, to))
	resp, err := c.client().Do(req)
	if err != nil {
		return nil, fmt.Errorf("%w: GET %s: %w", ErrFailed, Redacted(r.URL), unwrapURLErr(err))
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusPartialContent {
		return nil, fmt.Errorf("%w: GET %s range %d-%d: status %d: %s", ErrFailed, Redacted(r.URL), from, to,
			resp.StatusCode, snippet(resp.Body))
	}
	// Content-Range: bytes <from>-<to>/<object size>.
	if cr := resp.Header.Get("Content-Range"); !strings.HasSuffix(cr, fmt.Sprintf("/%d", r.size)) ||
		!strings.HasPrefix(cr, fmt.Sprintf("bytes %d-%d/", from, to)) {
		return nil, fmt.Errorf("%w: GET %s: Content-Range %q, want bytes %d-%d/%d", ErrMismatch, Redacted(r.URL), cr, from, to, r.size)
	}
	want := to - from + 1
	buf := make([]byte, want)
	if _, err := io.ReadFull(resp.Body, buf); err != nil {
		return nil, fmt.Errorf("%w: GET %s range %d-%d: %v", ErrFailed, Redacted(r.URL), from, to, err)
	}
	if extra, _ := resp.Body.Read(make([]byte, 1)); extra > 0 {
		return nil, fmt.Errorf("%w: GET %s range %d-%d: more than %d bytes", ErrMismatch, Redacted(r.URL), from, to, want)
	}
	return buf, nil
}

func (rr *rangeReader) Read(p []byte) (int, error) {
	for len(rr.cur) == 0 {
		if rr.err != nil {
			return 0, rr.err
		}
		if rr.next == len(rr.parts) {
			return 0, io.EOF
		}
		var res partResult
		select {
		case res = <-rr.parts[rr.next]:
		case <-rr.ctx.Done():
			// The timeout or Close stopped the dispatcher: this part may
			// never come.
			rr.err = fmt.Errorf("%w: %w", ErrFailed, rr.ctx.Err())
			return 0, rr.err
		}
		rr.next++
		<-rr.slots
		if res.err != nil {
			rr.err = res.err
			rr.cancel()
			return 0, res.err
		}
		rr.cur = res.data
	}
	n := copy(p, rr.cur)
	rr.cur = rr.cur[n:]
	return n, nil
}

func (rr *rangeReader) Close() error {
	rr.cancel()
	return nil
}
