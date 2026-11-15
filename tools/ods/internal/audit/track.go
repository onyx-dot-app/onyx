package audit

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"slices"
	"sort"
	"strings"
	"time"
)

// trackedCategoryPrefix starts the Security tab category of every image audit
// the deploy gate uploads, such as image-audit-sandbox.
const trackedCategoryPrefix = "image-audit-"

// FlagAge is how long a CVE stays open before the summary flags it.
const FlagAge = 90 * 24 * time.Hour

// CodeScanningAlert is the part of a GitHub code scanning alert the tracking
// reads.
type CodeScanningAlert struct {
	State     string    `json:"state"`
	CreatedAt time.Time `json:"created_at"`
	Rule      struct {
		ID                    string `json:"id"`
		Severity              string `json:"severity"`
		SecuritySeverityLevel string `json:"security_severity_level"`
	} `json:"rule"`
	MostRecentInstance struct {
		Category string `json:"category"`
	} `json:"most_recent_instance"`
}

// History is the per-image CVE count over time, one snapshot per day.
type History struct {
	Snapshots []Snapshot `json:"snapshots"`
}

// Snapshot counts the CVEs per image on one day.
type Snapshot struct {
	Date   string                   `json:"date"`
	Images map[string]ImageSnapshot `json:"images"`
}

// ImageSnapshot counts one image's CVEs: every one the Security tab has seen,
// split into open and resolved (fixed or dismissed).
type ImageSnapshot struct {
	Total          int            `json:"total"`
	Open           int            `json:"open"`
	Resolved       int            `json:"resolved"`
	OpenBySeverity map[string]int `json:"open_by_severity,omitempty"`
	// Flagged lists the CVEs open for FlagAge or longer.
	Flagged []FlaggedCVE `json:"flagged,omitempty"`
}

// FlaggedCVE is a CVE open for FlagAge or longer.
type FlaggedCVE struct {
	ID       string `json:"id"`
	Severity string `json:"severity"`
	Opened   string `json:"opened"`
	DaysOpen int    `json:"days_open"`
}

// BuildSnapshot counts the image audits' code scanning alerts per image. A CVE
// is one rule id per image: open while any of its alerts is open, and open
// since its earliest open alert.
func BuildSnapshot(alerts []CodeScanningAlert, now time.Time) Snapshot {
	type cve struct {
		open     bool
		opened   time.Time
		severity string
	}
	byImage := map[string]map[string]*cve{}
	for _, a := range alerts {
		image, ok := strings.CutPrefix(a.MostRecentInstance.Category, trackedCategoryPrefix)
		if !ok || image == "" || a.Rule.ID == "" {
			continue
		}
		if byImage[image] == nil {
			byImage[image] = map[string]*cve{}
		}
		c := byImage[image][a.Rule.ID]
		if c == nil {
			c = &cve{}
			byImage[image][a.Rule.ID] = c
		}
		c.severity = strings.ToLower(firstNonEmpty(c.severity, a.Rule.SecuritySeverityLevel, a.Rule.Severity, "unknown"))
		if a.State == "open" {
			if !c.open || a.CreatedAt.Before(c.opened) {
				c.opened = a.CreatedAt
			}
			c.open = true
		}
	}

	snap := Snapshot{Date: now.UTC().Format(time.DateOnly), Images: map[string]ImageSnapshot{}}
	for image, cves := range byImage {
		var s ImageSnapshot
		for id, c := range cves {
			s.Total++
			if !c.open {
				s.Resolved++
				continue
			}
			s.Open++
			if s.OpenBySeverity == nil {
				s.OpenBySeverity = map[string]int{}
			}
			s.OpenBySeverity[c.severity]++
			if age := now.Sub(c.opened); age >= FlagAge {
				s.Flagged = append(s.Flagged, FlaggedCVE{
					ID:       id,
					Severity: c.severity,
					Opened:   c.opened.UTC().Format(time.DateOnly),
					DaysOpen: int(age / (24 * time.Hour)),
				})
			}
		}
		sort.Slice(s.Flagged, func(i, j int) bool {
			if s.Flagged[i].DaysOpen != s.Flagged[j].DaysOpen {
				return s.Flagged[i].DaysOpen > s.Flagged[j].DaysOpen
			}
			return s.Flagged[i].ID < s.Flagged[j].ID
		})
		snap.Images[image] = s
	}
	return snap
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

// Record adds a snapshot, replacing one from the same day, and keeps the
// snapshots in date order.
func (h *History) Record(s Snapshot) {
	for i := range h.Snapshots {
		if h.Snapshots[i].Date == s.Date {
			h.Snapshots[i] = s
			return
		}
	}
	h.Snapshots = append(h.Snapshots, s)
	sort.Slice(h.Snapshots, func(i, j int) bool { return h.Snapshots[i].Date < h.Snapshots[j].Date })
}

// ReadHistory reads a history file. A missing file is an empty history, for
// the first run.
func ReadHistory(path string) (History, error) {
	var h History
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return h, nil
	}
	if err != nil {
		return h, err
	}
	if err := json.Unmarshal(data, &h); err != nil {
		return h, fmt.Errorf("failed to parse CVE history %s: %w", path, err)
	}
	return h, nil
}

// WriteHistory writes a history file.
func WriteHistory(path string, h History) error {
	data, err := json.MarshalIndent(h, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0644)
}

// RenderTrackSummary is the Slack summary of the latest snapshot: open,
// resolved, and total CVEs per image with the change in open CVEs since the
// snapshot a week earlier, then the CVEs open for FlagAge or longer.
func RenderTrackSummary(h History) string {
	if len(h.Snapshots) == 0 {
		return "*CVE tracking:* no snapshots yet."
	}
	latest := h.Snapshots[len(h.Snapshots)-1]
	var prev *Snapshot
	if day, err := time.Parse(time.DateOnly, latest.Date); err == nil {
		weekAgo := day.AddDate(0, 0, -7).Format(time.DateOnly)
		for i := len(h.Snapshots) - 2; i >= 0; i-- {
			if h.Snapshots[i].Date <= weekAgo {
				prev = &h.Snapshots[i]
				break
			}
		}
	}

	images := make([]string, 0, len(latest.Images))
	for image := range latest.Images {
		images = append(images, image)
	}
	// Most open CVEs first, so the image the most come from leads.
	sort.Slice(images, func(i, j int) bool {
		a, b := latest.Images[images[i]], latest.Images[images[j]]
		if a.Open != b.Open {
			return a.Open > b.Open
		}
		return images[i] < images[j]
	})

	var b strings.Builder
	fmt.Fprintf(&b, "*📊 CVEs per image, %s*\n", latest.Date)
	if len(images) == 0 {
		b.WriteString("No image audit alerts in the Security tab.\n")
	}
	for _, image := range images {
		s := latest.Images[image]
		change := ""
		if prev != nil {
			delta := s.Open - prev.Images[image].Open
			change = fmt.Sprintf(" (%+d open since %s)", delta, prev.Date)
		}
		fmt.Fprintf(&b, "• *%s*: %d open%s, %d resolved, %d total%s\n", image, s.Open, severityBreakdown(s.OpenBySeverity), s.Resolved, s.Total, change)
	}

	var flagged []string
	for _, image := range images {
		for _, f := range latest.Images[image].Flagged {
			flagged = append(flagged, fmt.Sprintf("• `%s` in *%s* (%s): open %d days, since %s", f.ID, image, f.Severity, f.DaysOpen, f.Opened))
		}
	}
	fmt.Fprintf(&b, "*🚩 Open %d+ days:* ", int(FlagAge/(24*time.Hour)))
	if len(flagged) == 0 {
		b.WriteString("none.")
	} else {
		fmt.Fprintf(&b, "%d\n%s", len(flagged), strings.Join(flagged, "\n"))
	}
	return b.String()
}

// severityOrder lists the Security tab severities, worst first.
var severityOrder = []string{"critical", "high", "medium", "low", "warning", "note", "error", "unknown"}

func severityBreakdown(counts map[string]int) string {
	var parts []string
	for _, sev := range severityOrder {
		if n := counts[sev]; n > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", n, sev))
		}
	}
	var other []string
	for sev, n := range counts {
		if n > 0 && !slices.Contains(severityOrder, sev) {
			other = append(other, fmt.Sprintf("%d %s", n, sev))
		}
	}
	sort.Strings(other)
	parts = append(parts, other...)
	if len(parts) == 0 {
		return ""
	}
	return " (" + strings.Join(parts, ", ") + ")"
}
