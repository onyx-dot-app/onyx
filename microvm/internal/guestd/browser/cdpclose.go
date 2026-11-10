package browser

import (
	"bufio"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"net"
	"net/http"
	"time"
)

// cdpClose sends the CDP command Browser.close on the browser WebSocket at
// addr+path. Chromium then shuts down its profile (cookies and other SQLite
// stores are committed). SIGTERM alone ends Chromium without that.
func cdpClose(addr, path string, timeout time.Duration) error {
	c, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return err
	}
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(timeout))
	key := make([]byte, 16)
	_, _ = rand.Read(key)
	// No Origin header: Chromium refuses WebSocket origins it does not allow.
	if _, err := fmt.Fprintf(c, "GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"+
		"Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n", path, addr, base64.StdEncoding.EncodeToString(key)); err != nil {
		return err
	}
	resp, err := http.ReadResponse(bufio.NewReader(c), nil)
	if err != nil {
		return err
	}
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusSwitchingProtocols {
		return fmt.Errorf("websocket upgrade: HTTP %d", resp.StatusCode)
	}
	msg := []byte(`{"id":1,"method":"Browser.close"}`)
	// One masked text frame (client frames must be masked, RFC 6455).
	frame := []byte{0x81, 0x80 | byte(len(msg))}
	mask := make([]byte, 4)
	_, _ = rand.Read(mask)
	frame = append(frame, mask...)
	for i, b := range msg {
		frame = append(frame, b^mask[i%4])
	}
	_, err = c.Write(frame)
	return err
}
