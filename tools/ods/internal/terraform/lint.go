// Package terraform implements the Terraform checks that ods runs in place of
// tools that need a local terraform binary.
package terraform

import (
	"bytes"
	"fmt"
	"net/netip"
	"os"
	"regexp"
)

// Findings name the rule they broke so callers can group or filter them.
const (
	RuleAccessKey = "access_key"
	RuleEmail     = "email"
	RuleCIDR      = "cidr"
	RuleAccountID = "account_id"
)

var ruleMessages = map[string]string{
	RuleAccessKey: "AWS access key id",
	RuleEmail:     "email address",
	RuleAccountID: "12-digit value that looks like an AWS account id",
	RuleCIDR:      "routable IPv4 CIDR",
}

// allowMarker must be the whole trailing comment token, so that
// "# public-safe: okay" does not silence a line.
var allowMarker = regexp.MustCompile(`#\s*public-safe:\s*ok\s*$`)

// suspect is a single pass over the file. Nothing else touches the bytes unless
// this matches, which keeps the common case (a clean file) to one scan.
//
// Alternatives are ordered so the more specific pattern wins at a given
// position; the matching group names the rule. RE2 has no lookaround, so
// account_id takes a whole digit run and lets checkAccountID reject runs that
// are not exactly 12 long -- the same thing Python's (?<!\d)\d{12}(?!\d) does.
var suspect = regexp.MustCompile(
	`(?P<access_key>\b(?:AKIA|ASIA)[0-9A-Z]{16}\b)` +
		`|(?P<email>\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)` +
		`|(?P<cidr>\b[0-9]{1,3}(?:\.[0-9]{1,3}){3}/[0-9]{1,2}\b)` +
		`|(?P<account_id>[0-9]{12,})`,
)

// Finding is one rule violation at one line.
type Finding struct {
	Path  string
	Line  int
	Rule  string
	Value string
}

func (f Finding) String() string {
	return fmt.Sprintf("%s:%d: %s %s", f.Path, f.Line, ruleMessages[f.Rule], f.Value)
}

// LintFile scans one Terraform file for values that must not be published.
// display is the path used in findings, so callers can show a repo-relative one.
func LintFile(path, display string) ([]Finding, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return lintBytes(data, display), nil
}

func lintBytes(data []byte, display string) []Finding {
	// Fast path: one scan, no allocation, and almost always the answer.
	if !suspect.Match(data) {
		return nil
	}

	var findings []Finding
	// Matches come back in order, so line numbers only need a forward walk.
	line, scanned := 1, 0

	for _, m := range suspect.FindAllSubmatchIndex(data, -1) {
		start, end := m[0], m[1]
		rule := matchedRule(m)
		value := data[start:end]

		line += bytes.Count(data[scanned:start], []byte("\n"))
		scanned = start

		if !ruleApplies(rule, value) {
			continue
		}
		if allowMarker.Match(lineAt(data, start)) {
			continue
		}
		findings = append(findings, Finding{
			Path:  display,
			Line:  line,
			Rule:  rule,
			Value: string(value),
		})
	}
	return findings
}

// matchedRule names the alternative that fired. Group 0 is the whole match.
func matchedRule(m []int) string {
	names := suspect.SubexpNames()
	for i := 1; i < len(names); i++ {
		if m[2*i] >= 0 {
			return names[i]
		}
	}
	return ""
}

// ruleApplies runs the per-rule checks that the shared regex cannot express.
func ruleApplies(rule string, value []byte) bool {
	switch rule {
	case RuleAccountID:
		// A longer digit run is an id of some other kind, not an account id.
		return len(value) == 12
	case RuleCIDR:
		p, err := netip.ParsePrefix(string(value))
		if err != nil || !p.Addr().Is4() {
			return false
		}
		// A private or reserved range is fine to ship; a routable one is not.
		return !isPublishableCIDR(p)
	default:
		return true
	}
}

// lineAt returns the whole line containing off, without copying the file.
func lineAt(data []byte, off int) []byte {
	start := bytes.LastIndexByte(data[:off], '\n') + 1
	end := bytes.IndexByte(data[off:], '\n')
	if end < 0 {
		return data[start:]
	}
	return data[start : off+end]
}
