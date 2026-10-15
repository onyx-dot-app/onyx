package install

import (
	"crypto/rand"
	"encoding/hex"
)

// randomHex returns n random bytes hex-encoded (install.sh: openssl rand -hex n).
func randomHex(n int) string {
	buf := make([]byte, n)
	if _, err := rand.Read(buf); err != nil {
		// crypto/rand failure means the platform's entropy source is broken;
		// panicking beats silently generating weak secrets.
		panic(err)
	}
	return hex.EncodeToString(buf)
}
