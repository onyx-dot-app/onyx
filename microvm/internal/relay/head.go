package relay

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"
)

// MaxHeadBytes bounds the request head the relay reads.
const MaxHeadBytes = 64 << 10

// SessionHintHeader carries the session tag from the proxy URL userinfo.
const SessionHintHeader = "X-Onyx-Session-Hint"

// ErrBadHead means the request head is not strict HTTP/1.x.
var ErrBadHead = errors.New("malformed request head")

type headerField struct {
	name, value string
}

// Head is one parsed request head.
type Head struct {
	Method  string
	Target  string
	Version string
	fields  []headerField
}

// IsConnect reports a CONNECT request.
func (h *Head) IsConnect() bool { return h.Method == "CONNECT" }

func (h *Head) get(name string) (string, bool) {
	for _, f := range h.fields {
		if strings.EqualFold(f.name, name) {
			return f.value, true
		}
	}
	return "", false
}

func (h *Head) del(name string) {
	out := h.fields[:0]
	for _, f := range h.fields {
		if !strings.EqualFold(f.name, name) {
			out = append(out, f)
		}
	}
	h.fields = out
}

// ReadHead reads one request head. It rejects a bare LF, obs-fold, a head
// over MaxHeadBytes and a malformed request line or field.
func ReadHead(r *bufio.Reader) (*Head, error) {
	var lines []string
	total := 0
	for {
		line, err := r.ReadSlice('\n')
		total += len(line)
		if total > MaxHeadBytes {
			return nil, fmt.Errorf("%w: head over %d bytes", ErrBadHead, MaxHeadBytes)
		}
		if errors.Is(err, bufio.ErrBufferFull) {
			return nil, fmt.Errorf("%w: line too long", ErrBadHead)
		}
		if err != nil {
			return nil, err
		}
		if len(line) < 2 || line[len(line)-2] != '\r' {
			return nil, fmt.Errorf("%w: bare LF", ErrBadHead)
		}
		s := string(line[:len(line)-2])
		if strings.ContainsAny(s, "\r\x00") {
			return nil, fmt.Errorf("%w: CR or NUL in a line", ErrBadHead)
		}
		if s == "" {
			if len(lines) == 0 {
				return nil, fmt.Errorf("%w: empty head", ErrBadHead)
			}
			break
		}
		lines = append(lines, s)
	}
	parts := strings.Split(lines[0], " ")
	if len(parts) != 3 || !isToken(parts[0]) || parts[1] == "" || (parts[2] != "HTTP/1.1" && parts[2] != "HTTP/1.0") {
		return nil, fmt.Errorf("%w: request line %q", ErrBadHead, lines[0])
	}
	h := &Head{Method: parts[0], Target: parts[1], Version: parts[2]}
	for _, l := range lines[1:] {
		if l[0] == ' ' || l[0] == '\t' {
			return nil, fmt.Errorf("%w: obs-fold", ErrBadHead)
		}
		name, value, ok := strings.Cut(l, ":")
		if !ok || !isToken(name) {
			return nil, fmt.Errorf("%w: field %q", ErrBadHead, l)
		}
		h.fields = append(h.fields, headerField{name: name, value: strings.Trim(value, " \t")})
	}
	return h, nil
}

// Stamp replaces the VM's identity headers with the relay's.
//
//   - Proxy-Authorization and X-Onyx-Session-Hint from the VM are removed.
//   - The user name in a Basic Proxy-Authorization (the proxy URL userinfo)
//     becomes the session hint.
//   - A plain request that is not an Upgrade gets "Connection: close": the
//     relay stamps one head per connection, and the proxy accepts one request
//     per signed connection.
func (h *Head) Stamp(token string) {
	hint := sessionHint(h)
	h.del("Proxy-Authorization")
	h.del(SessionHintHeader)
	if !h.IsConnect() {
		if _, upgrade := h.get("Upgrade"); !upgrade {
			h.del("Connection")
			h.del("Proxy-Connection")
			h.del("Keep-Alive")
			h.fields = append(h.fields, headerField{"Connection", "close"})
		}
	}
	h.fields = append(h.fields, headerField{"Proxy-Authorization", "Bearer " + token})
	if hint != "" {
		h.fields = append(h.fields, headerField{SessionHintHeader, hint})
	}
}

// sessionHint returns the user name of a Basic Proxy-Authorization, if it is
// plain visible ASCII.
func sessionHint(h *Head) string {
	v, ok := h.get("Proxy-Authorization")
	if !ok {
		return ""
	}
	scheme, cred, _ := strings.Cut(v, " ")
	if !strings.EqualFold(scheme, "basic") {
		return ""
	}
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(cred))
	if err != nil {
		return ""
	}
	user, _, _ := strings.Cut(string(raw), ":")
	if user == "" || len(user) > 256 {
		return ""
	}
	for i := 0; i < len(user); i++ {
		if user[i] < 0x21 || user[i] > 0x7e {
			return ""
		}
	}
	return user
}

// Bytes serializes the head with CRLF line ends.
func (h *Head) Bytes() []byte {
	var b bytes.Buffer
	b.WriteString(h.Method + " " + h.Target + " " + h.Version + "\r\n")
	for _, f := range h.fields {
		b.WriteString(f.name + ": " + f.value + "\r\n")
	}
	b.WriteString("\r\n")
	return b.Bytes()
}

func isToken(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c <= 0x20 || c >= 0x7f || strings.IndexByte(`()<>@,;:\"/[]?={}`, c) >= 0 {
			return false
		}
	}
	return true
}
