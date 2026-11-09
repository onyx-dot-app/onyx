package hostinfo

import (
	"strings"
	"testing"
)

func TestParseMemInfo(t *testing.T) {
	total, avail, err := parseMemInfo(strings.NewReader("MemTotal:       64775184 kB\nMemFree:  1 kB\nMemAvailable:   62916612 kB\n"))
	if err != nil || total != 63257 || avail != 61442 {
		t.Fatalf("got %d %d %v", total, avail, err)
	}
	if _, _, err := parseMemInfo(strings.NewReader("MemTotal: 1 kB\n")); err == nil {
		t.Fatal("no error without MemAvailable")
	}
}
