package terraform

import (
	"net/netip"
	"testing"
)

// The expectations come from CPython's `IPv4Network.is_global`, which the
// original check_public_safe.py used.
func TestIsPublishableCIDR(t *testing.T) {
	tests := []struct {
		cidr string
		want bool
	}{
		// "anywhere" leaks nothing.
		{"0.0.0.0/0", true},

		// Private and reserved ranges.
		{"0.0.0.0/8", true},
		{"10.0.0.0/8", true},
		{"127.0.0.1/32", true},
		{"169.254.0.0/16", true},
		{"172.16.0.0/12", true},
		{"192.0.0.0/24", true},
		{"192.0.2.0/24", true},
		{"192.168.1.0/24", true},
		{"198.18.0.0/15", true},
		{"198.51.100.0/24", true},
		{"203.0.113.0/24", true},
		{"203.0.113.5/32", true},
		{"240.0.0.0/4", true},
		{"255.255.255.255/32", true},

		// Carrier-grade NAT is unroutable but is not in the private list.
		{"100.64.0.0/10", true},
		{"100.64.1.0/24", true},
		{"100.128.0.0/9", false},

		// Routable addresses.
		{"8.8.8.8/32", false},
		{"1.1.1.1/32", false},
		{"172.32.0.0/12", false},
		{"192.31.196.0/24", false},
		{"192.88.99.0/24", false},
		{"224.0.0.0/4", false},

		// Carved out of 192.0.0.0/24 and still routable.
		{"192.0.0.9/32", false},
		{"192.0.0.10/32", false},

		// A prefix wide enough to span a routable gap is not publishable,
		// even though both of its endpoints are unroutable.
		{"0.0.0.0/1", false},
		{"192.0.0.0/2", false},
	}

	for _, tt := range tests {
		t.Run(tt.cidr, func(t *testing.T) {
			p, err := netip.ParsePrefix(tt.cidr)
			if err != nil {
				t.Fatal(err)
			}
			if got := isPublishableCIDR(p); got != tt.want {
				t.Errorf("isPublishableCIDR(%s) = %v, want %v", tt.cidr, got, tt.want)
			}
		})
	}
}

func TestLastAddr(t *testing.T) {
	tests := []struct{ cidr, want string }{
		{"10.0.0.0/8", "10.255.255.255"},
		{"192.168.1.0/24", "192.168.1.255"},
		{"8.8.8.8/32", "8.8.8.8"},
		{"0.0.0.0/0", "255.255.255.255"},
		{"192.0.0.170/31", "192.0.0.171"},
	}

	for _, tt := range tests {
		t.Run(tt.cidr, func(t *testing.T) {
			got := lastAddr(netip.MustParsePrefix(tt.cidr).Masked())
			if got.String() != tt.want {
				t.Errorf("lastAddr(%s) = %s, want %s", tt.cidr, got, tt.want)
			}
		})
	}
}
