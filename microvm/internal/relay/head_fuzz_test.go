package relay

import (
	"bufio"
	"bytes"
	"strings"
	"testing"
)

// FuzzReadHead feeds guest bytes to the head parser. A head that parses must,
// after Stamp, parse again with exactly the relay's credential and at most
// one session hint: the guest cannot smuggle its own identity headers.
//
//	go test -run '^$' -fuzz FuzzReadHead -fuzztime 60s ./internal/relay
func FuzzReadHead(f *testing.F) {
	for _, seed := range []string{
		"CONNECT pypi.org:443 HTTP/1.1\r\nHost: pypi.org:443\r\n\r\n",
		"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\nProxy-Authorization: Basic c2Vzcy0xOng=\r\n\r\n",
		"GET http://example.com/ HTTP/1.0\r\nproxy-authorization: Bearer forged\r\nX-Onyx-Session-Hint: other\r\nConnection: keep-alive\r\n\r\n",
		"GET / HTTP/1.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n",
		"GET / HTTP/1.1\r\n folded: x\r\n\r\n",
		"GET / HTTP/1.1\nHost: x\n\n",
		"GET / HTTP/1.1\r\nHost: a\x00b\r\n\r\n",
	} {
		f.Add([]byte(seed))
	}
	const token = "relay-token"
	f.Fuzz(func(t *testing.T, in []byte) {
		h, err := ReadHead(bufio.NewReader(bytes.NewReader(in)))
		if err != nil {
			return
		}
		h.Stamp(token)
		out := h.Bytes()
		again, err := ReadHead(bufio.NewReader(bytes.NewReader(out)))
		if err != nil {
			t.Fatalf("stamped head does not parse: %v\n%q", err, out)
		}
		if again.Method != h.Method || again.Target != h.Target || again.Version != h.Version {
			t.Fatalf("request line changed: %q", out)
		}
		auth, hints := 0, 0
		for _, fl := range again.fields {
			switch {
			case strings.EqualFold(fl.name, "Proxy-Authorization"):
				auth++
				if fl.value != "Bearer "+token {
					t.Fatalf("guest credential kept: %q", out)
				}
			case strings.EqualFold(fl.name, SessionHintHeader):
				hints++
			}
		}
		if auth != 1 || hints > 1 {
			t.Fatalf("%d credentials, %d session hints after Stamp: %q", auth, hints, out)
		}
	})
}
