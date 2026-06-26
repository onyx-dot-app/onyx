package audit

import (
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"
)

// render writes the result to w in the requested format.
func render(w io.Writer, format string, res *Result) error {
	switch strings.ToLower(strings.TrimSpace(format)) {
	case "", "text":
		return renderText(w, res)
	case "json":
		return renderJSON(w, res)
	case "sarif":
		return renderSARIF(w, res)
	default:
		return fmt.Errorf("unknown format %q (want text, json, or sarif)", format)
	}
}

func renderText(w io.Writer, res *Result) error {
	if len(res.Findings) == 0 {
		_, _ = fmt.Fprintln(w, "No dependency vulnerabilities found.")
		if len(res.Ignored) > 0 {
			_, _ = fmt.Fprintf(w, "(%d suppressed by allowlist)\n", len(res.Ignored))
		}
		return nil
	}

	_, _ = fmt.Fprintln(w, "Dependency vulnerabilities:")
	for _, f := range res.Findings {
		version := f.Package
		if f.Version != "" {
			version = f.Package + "@" + f.Version
		}
		_, _ = fmt.Fprintf(w, "  %-9s %-9s %-22s %-28s %s",
			strings.ToUpper(string(f.Severity)),
			f.Ecosystem,
			f.ID,
			truncate(version, 28),
			truncate(f.Title, 60),
		)
		if f.Source == SourceDependabot {
			_, _ = fmt.Fprint(w, " [dependabot]")
		}
		_, _ = fmt.Fprintln(w)
	}

	_, _ = fmt.Fprintf(w, "\n%s\n", summaryLine(res))
	return nil
}

// summaryLine builds a one-line tally of findings by severity.
func summaryLine(res *Result) string {
	counts := map[Severity]int{}
	for _, f := range res.Findings {
		counts[f.Severity]++
	}
	var parts []string
	for _, s := range []Severity{SeverityCritical, SeverityHigh, SeverityModerate, SeverityLow, SeverityUnknown} {
		if counts[s] > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", counts[s], s))
		}
	}
	line := fmt.Sprintf("%d findings", len(res.Findings))
	if len(parts) > 0 {
		line += " (" + strings.Join(parts, ", ") + ")"
	}
	if len(res.Ignored) > 0 {
		line += fmt.Sprintf("; %d suppressed by allowlist", len(res.Ignored))
	}
	if len(res.Blocking) > 0 {
		line += fmt.Sprintf("; %d blocking", len(res.Blocking))
	}
	return line
}

func renderJSON(w io.Writer, res *Result) error {
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(res)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if n <= 1 {
		return s[:n]
	}
	return s[:n-1] + "…"
}

// --- SARIF 2.1.0 ---

const (
	sarifSchema  = "https://json.schemastore.org/sarif-2.1.0.json"
	sarifVersion = "2.1.0"
	sarifToolURI = "https://github.com/onyx-dot-app/onyx"
)

type sarifLog struct {
	Schema  string     `json:"$schema"`
	Version string     `json:"version"`
	Runs    []sarifRun `json:"runs"`
}

type sarifRun struct {
	Tool    sarifTool     `json:"tool"`
	Results []sarifResult `json:"results"`
}

type sarifTool struct {
	Driver sarifDriver `json:"driver"`
}

type sarifDriver struct {
	Name           string      `json:"name"`
	InformationURI string      `json:"informationUri,omitempty"`
	Rules          []sarifRule `json:"rules"`
}

type sarifRule struct {
	ID               string         `json:"id"`
	Name             string         `json:"name,omitempty"`
	ShortDescription sarifText      `json:"shortDescription"`
	HelpURI          string         `json:"helpUri,omitempty"`
	Properties       map[string]any `json:"properties,omitempty"`
}

type sarifResult struct {
	RuleID     string          `json:"ruleId"`
	Level      string          `json:"level"`
	Message    sarifText       `json:"message"`
	Locations  []sarifLocation `json:"locations,omitempty"`
	Properties map[string]any  `json:"properties,omitempty"`
}

type sarifText struct {
	Text string `json:"text"`
}

type sarifLocation struct {
	PhysicalLocation sarifPhysicalLocation `json:"physicalLocation"`
}

type sarifPhysicalLocation struct {
	ArtifactLocation sarifArtifactLocation `json:"artifactLocation"`
}

type sarifArtifactLocation struct {
	URI string `json:"uri"`
}

// sarifLevel maps a Severity to a SARIF result level.
func sarifLevel(s Severity) string {
	switch s {
	case SeverityCritical, SeverityHigh:
		return "error"
	case SeverityModerate:
		return "warning"
	default:
		return "note"
	}
}

func renderSARIF(w io.Writer, res *Result) error {
	rules := make([]sarifRule, 0)
	seenRule := map[string]bool{}
	results := make([]sarifResult, 0, len(res.Findings))

	for _, f := range res.Findings {
		if !seenRule[f.ID] {
			seenRule[f.ID] = true
			rules = append(rules, sarifRule{
				ID:               f.ID,
				Name:             f.ID,
				ShortDescription: sarifText{Text: ruleDescription(f)},
				HelpURI:          f.URL,
				Properties: map[string]any{
					"security-severity": securitySeverityScore(f.Severity),
					"tags":              []string{"security", "dependency"},
				},
			})
		}

		message := fmt.Sprintf("%s: %s", packageVersion(f), f.Title)
		if f.FixedIn != "" {
			message += fmt.Sprintf(" (fixed in %s)", f.FixedIn)
		}

		result := sarifResult{
			RuleID:  f.ID,
			Level:   sarifLevel(f.Severity),
			Message: sarifText{Text: message},
			Properties: map[string]any{
				"severity":  string(f.Severity),
				"ecosystem": f.Ecosystem,
				"package":   f.Package,
				"source":    f.Source,
			},
		}
		if f.Manifest != "" {
			result.Locations = []sarifLocation{{
				PhysicalLocation: sarifPhysicalLocation{
					ArtifactLocation: sarifArtifactLocation{URI: f.Manifest},
				},
			}}
		}
		results = append(results, result)
	}

	sort.SliceStable(rules, func(i, j int) bool { return rules[i].ID < rules[j].ID })

	doc := sarifLog{
		Schema:  sarifSchema,
		Version: sarifVersion,
		Runs: []sarifRun{{
			Tool: sarifTool{Driver: sarifDriver{
				Name:           "ods-audit",
				InformationURI: sarifToolURI,
				Rules:          rules,
			}},
			Results: results,
		}},
	}

	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(doc)
}

func ruleDescription(f Finding) string {
	if f.Title != "" {
		return f.Title
	}
	return fmt.Sprintf("%s affects %s", f.ID, f.Package)
}

func packageVersion(f Finding) string {
	if f.Version != "" {
		return f.Package + "@" + f.Version
	}
	return f.Package
}

// securitySeverityScore maps a Severity to the numeric "security-severity"
// string GitHub code scanning uses to bucket SARIF results.
func securitySeverityScore(s Severity) string {
	switch s {
	case SeverityCritical:
		return "9.0"
	case SeverityHigh:
		return "7.0"
	case SeverityModerate:
		return "4.0"
	case SeverityLow:
		return "1.0"
	default:
		return "0.0"
	}
}
