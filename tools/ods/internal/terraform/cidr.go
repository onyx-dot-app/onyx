package terraform

import "net/netip"

// privateV4 lists the IPv4 ranges that are safe to publish: a reader cannot
// route to them, so they carry no information about our infrastructure. The set
// mirrors the iana-ipv4-special-registry ranges CPython's `ipaddress` uses.
var privateV4 = mustPrefixes(
	"0.0.0.0/8",
	"10.0.0.0/8",
	"127.0.0.0/8",
	"169.254.0.0/16",
	"172.16.0.0/12",
	"192.0.0.0/24",
	"192.0.0.170/31",
	"192.0.2.0/24",
	"192.168.0.0/16",
	"198.18.0.0/15",
	"198.51.100.0/24",
	"203.0.113.0/24",
	"240.0.0.0/4",
	"255.255.255.255/32",
)

// privateExceptionsV4 are carved out of 192.0.0.0/24 and stay routable.
var privateExceptionsV4 = mustPrefixes(
	"192.0.0.9/32",
	"192.0.0.10/32",
)

// cgnatV4 is the carrier-grade NAT block. It is not in the private list, but it
// is unroutable, so it gets the same treatment.
var cgnatV4 = netip.MustParsePrefix("100.64.0.0/10")

func mustPrefixes(raw ...string) []netip.Prefix {
	out := make([]netip.Prefix, 0, len(raw))
	for _, s := range raw {
		out = append(out, netip.MustParsePrefix(s))
	}
	return out
}

// isPublishableCIDR reports whether a CIDR is safe to ship in a public module.
//
// "0.0.0.0/0" is allowed outright: it means "anywhere", so it leaks nothing.
// Otherwise the whole prefix must fall inside one unroutable range. A prefix
// that spans two such ranges, or straddles a routable gap between them, stays
// routable as a whole and is not publishable.
func isPublishableCIDR(p netip.Prefix) bool {
	p = p.Masked()
	if p.Bits() == 0 && p.Addr().IsUnspecified() {
		return true
	}

	first, last := p.Addr(), lastAddr(p)
	if cgnatV4.Contains(first) && cgnatV4.Contains(last) {
		return true
	}

	within := false
	for _, n := range privateV4 {
		if n.Contains(first) && n.Contains(last) {
			within = true
			break
		}
	}
	if !within {
		return false
	}
	for _, exc := range privateExceptionsV4 {
		if exc.Contains(first) || exc.Contains(last) {
			return false
		}
	}
	return true
}

// lastAddr returns the broadcast address of a masked IPv4 prefix.
func lastAddr(p netip.Prefix) netip.Addr {
	octets := p.Addr().As4()
	for i := p.Bits(); i < 32; i++ {
		octets[i/8] |= 1 << (7 - i%8)
	}
	return netip.AddrFrom4(octets)
}
