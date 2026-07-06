package audit

// GitHub Actions dependency audit.
//
// osv-scalibr's github/actions extractor can *discover* the actions referenced by
// .github/workflows/*.{yml,yaml}, but as of osv-scanner v2.4.0 the scanner cannot
// *match* them against advisories: semantic.Parse has no comparator for the
// "GitHub Actions" ecosystem, so IsAffected returns false for every action (in
// both online and offline modes). GitHub Actions advisories also carry only
// ECOSYSTEM version ranges (no enumerated versions, no affected commits), which
// OSV.dev's version-query endpoint cannot evaluate.
//
// We therefore use the extractor purely for discovery and do our own matching:
// query OSV.dev for advisories by action name, resolve each SHA-pinned ref to its
// release tag via the GitHub CLI (the security-recommended pinning style leaves us
// only a commit to work with), and evaluate the advisory's ECOSYSTEM ranges with a
// semver comparator. A pin we can't resolve to a comparable version is surfaced as
// an unverified (non-blocking) finding rather than silently dropped.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	cpb "github.com/google/osv-scalibr/binary/proto/config_go_proto"
	"github.com/google/osv-scalibr/extractor/filesystem"
	"github.com/google/osv-scalibr/extractor/filesystem/misc/githubactions"
	"github.com/google/osv-scalibr/purl"
	log "github.com/sirupsen/logrus"
	"gopkg.in/yaml.v3"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/version"
)

const (
	// actionsEcosystem is the OSV ecosystem name for GitHub Actions advisories.
	actionsEcosystem = "GitHub Actions"
	// osvQueryURL is the OSV.dev single-package query endpoint.
	osvQueryURL = "https://api.osv.dev/v1/query"
)

// actionRef is a single `uses:` reference discovered in a workflow file.
type actionRef struct {
	Name     string // owner/repo
	Ref      string // git tag or 40-char commit SHA
	IsSHA    bool   // Ref is a full commit SHA (needs tag resolution to compare)
	Manifest string // repo-relative workflow path the ref came from
}

// scanActions discovers the actions used across the repo's workflows and
// composite actions and matches them against OSV.dev advisories. Returns nil when
// nothing is referenced or no advisories affect any used action.
func scanActions() ([]Finding, error) {
	root, err := paths.GitRoot()
	if err != nil {
		return nil, err
	}
	refs, err := extractActions(root)
	if err != nil {
		return nil, err
	}
	refs = dedupeRefs(refs)
	if len(refs) == 0 {
		return nil, nil
	}

	client := &http.Client{Timeout: 30 * time.Second}

	// Query advisories once per unique action name.
	advisories := make(map[string][]osvVuln)
	names := uniqueActionNames(refs)
	failed := 0
	for _, name := range names {
		vulns, err := queryActionAdvisories(client, name)
		if err != nil {
			// A single flaky query shouldn't sink the whole audit; the lockfile
			// scan is the primary gate. Warn and treat the action as clean.
			log.Warnf("OSV query failed for action %s: %v", name, err)
			failed++
			continue
		}
		if len(vulns) > 0 {
			advisories[name] = vulns
		}
	}
	// If every query failed, OSV.dev is effectively unavailable; surface that as a
	// scan error rather than reporting a clean, no-findings result.
	if failed > 0 && failed == len(names) {
		return nil, fmt.Errorf("all %d OSV.dev advisory queries failed", failed)
	}
	if len(advisories) == 0 {
		return nil, nil
	}

	// Only actions with advisories need version resolution, so tag lookups (the
	// expensive part) run for a handful of actions at most.
	tagCache := make(map[string][]ghTag)
	var findings []Finding
	for _, ref := range refs {
		vulns := advisories[ref.Name]
		if len(vulns) == 0 {
			continue
		}
		version, resolved := actionVersion(ref, tagCache)
		for _, v := range vulns {
			if !resolved {
				findings = append(findings, actionFinding(ref, v, false))
				continue
			}
			if affectedByAdvisory(version, v) {
				findings = append(findings, actionFinding(ref, v, true))
			}
		}
	}
	return findings, nil
}

// extractActions discovers the actions referenced across the repo's reusable
// workflows (.github/workflows) and composite actions (.github/actions). Returns
// nil when neither exists.
func extractActions(root string) ([]actionRef, error) {
	ext, err := githubactions.New(&cpb.PluginConfig{})
	if err != nil {
		return nil, err
	}

	workflowRefs, err := extractWorkflowActions(ext, root)
	if err != nil {
		return nil, err
	}
	compositeRefs, err := extractCompositeActions(ext, root)
	if err != nil {
		return nil, err
	}
	return append(workflowRefs, compositeRefs...), nil
}

// extractWorkflowActions runs the github/actions extractor over each
// .github/workflows/*.{yml,yaml} file.
func extractWorkflowActions(ext filesystem.Extractor, root string) ([]actionRef, error) {
	dir := filepath.Join(root, ".github", "workflows")
	entries, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	var refs []actionRef
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		if suffix := filepath.Ext(e.Name()); suffix != ".yml" && suffix != ".yaml" {
			continue
		}
		path := filepath.Join(dir, e.Name())
		f, err := os.Open(path)
		if err != nil {
			return nil, err
		}
		manifest := filepath.ToSlash(filepath.Join(".github", "workflows", e.Name()))
		rs, err := usesFromReader(ext, path, f, manifest)
		_ = f.Close()
		if err != nil {
			log.Warnf("Skipping workflow %s: %v", e.Name(), err)
			continue
		}
		refs = append(refs, rs...)
	}
	return refs, nil
}

// extractCompositeActions discovers the actions referenced by composite actions
// under .github/actions. The github/actions extractor only understands workflow
// files (jobs.<id>.steps[].uses), so each composite action's runs.steps is
// reshaped into a synthetic single-job workflow before extraction — reusing the
// extractor's uses parsing (subpaths, docker/local skips, SHA detection) rather
// than reimplementing it.
func extractCompositeActions(ext filesystem.Extractor, root string) ([]actionRef, error) {
	dir := filepath.Join(root, ".github", "actions")
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		return nil, nil
	}

	var refs []actionRef
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || (d.Name() != "action.yml" && d.Name() != "action.yaml") {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		manifest := path
		if rel, err := filepath.Rel(root, path); err == nil {
			manifest = rel
		}
		manifest = filepath.ToSlash(manifest)
		steps, err := compositeSteps(data)
		if err != nil {
			// A broken action.yml would otherwise drop its nested uses from the
			// audit silently; warn so the skipped coverage is visible.
			log.Warnf("Skipping unparseable composite action %s: %v", manifest, err)
			return nil
		}
		if len(steps) == 0 {
			return nil
		}
		wrapped, err := yaml.Marshal(map[string]any{
			"jobs": map[string]any{"composite": map[string]any{"steps": steps}},
		})
		if err != nil {
			return err
		}
		rs, err := usesFromReader(ext, path, bytes.NewReader(wrapped), manifest)
		if err != nil {
			log.Warnf("Skipping composite action %s: %v", manifest, err)
			return nil
		}
		refs = append(refs, rs...)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return refs, nil
}

// compositeSteps returns the runs.steps of a composite action.yml. It returns a
// nil slice and nil error for a valid but non-composite action (Docker and
// JavaScript actions reference no other actions), and a non-nil error only when
// the file can't be parsed as YAML — so callers can distinguish a clean skip from
// a broken file whose dependencies would otherwise vanish from the audit.
func compositeSteps(data []byte) ([]any, error) {
	var doc map[string]any
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return nil, err
	}
	runs, ok := doc["runs"].(map[string]any)
	if !ok {
		return nil, nil
	}
	if using, _ := runs["using"].(string); !strings.EqualFold(using, "composite") {
		return nil, nil
	}
	steps, _ := runs["steps"].([]any)
	return steps, nil
}

// usesFromReader runs the extractor over a workflow document and maps the
// referenced GitHub actions into actionRefs tagged with the given manifest path.
func usesFromReader(ext filesystem.Extractor, path string, r io.Reader, manifest string) ([]actionRef, error) {
	inv, err := ext.Extract(context.Background(), &filesystem.ScanInput{Path: path, Reader: r})
	if err != nil {
		return nil, err
	}
	var refs []actionRef
	for _, pkg := range inv.Packages {
		if pkg.PURLType != purl.TypeGithub {
			continue
		}
		ref := actionRef{Name: pkg.Name, Ref: pkg.Version, Manifest: manifest}
		// The extractor records the ref as a source-code commit only when it is a
		// full 40-char SHA, which is exactly when we need tag resolution.
		if pkg.SourceCode != nil && pkg.SourceCode.Commit != "" {
			ref.IsSHA = true
		}
		refs = append(refs, ref)
	}
	return refs, nil
}

// dedupeRefs collapses identical name@ref pairs, keeping the first manifest seen.
func dedupeRefs(refs []actionRef) []actionRef {
	seen := make(map[string]bool, len(refs))
	out := refs[:0]
	for _, r := range refs {
		key := r.Name + "@" + r.Ref
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, r)
	}
	return out
}

// uniqueActionNames returns the distinct owner/repo names across refs.
func uniqueActionNames(refs []actionRef) []string {
	seen := make(map[string]bool, len(refs))
	var names []string
	for _, r := range refs {
		if seen[r.Name] {
			continue
		}
		seen[r.Name] = true
		names = append(names, r.Name)
	}
	return names
}

// actionVersion resolves a ref to a semver-comparable version. Tag refs are used
// directly; SHA pins are resolved to their highest release tag via the GitHub CLI.
// The bool is false when no comparable version could be determined.
func actionVersion(ref actionRef, cache map[string][]ghTag) (string, bool) {
	if !ref.IsSHA {
		if version.IsSemverish(ref.Ref) {
			return version.Normalize(ref.Ref), true
		}
		return "", false
	}
	tags, ok := cache[ref.Name]
	if !ok {
		t, err := resolveActionTags(ref.Name)
		if err != nil {
			log.Warnf("Could not resolve tags for %s: %v", ref.Name, err)
		}
		tags = t
		cache[ref.Name] = tags
	}
	return versionForSHA(tags, ref.Ref)
}

// --- OSV.dev query ---

// osvVuln is the subset of an OSV.dev vulnerability record we consume.
type osvVuln struct {
	ID               string         `json:"id"`
	Aliases          []string       `json:"aliases"`
	Summary          string         `json:"summary"`
	Details          string         `json:"details"`
	Affected         []osvAffected  `json:"affected"`
	DatabaseSpecific map[string]any `json:"database_specific"`
}

type osvAffected struct {
	Package  osvPackage `json:"package"`
	Ranges   []osvRange `json:"ranges"`
	Versions []string   `json:"versions"`
}

type osvPackage struct {
	Ecosystem string `json:"ecosystem"`
	Name      string `json:"name"`
}

type osvRange struct {
	Type   string              `json:"type"`
	Events []map[string]string `json:"events"`
}

// queryActionAdvisories asks OSV.dev for advisories affecting an action, querying
// by name only. GitHub Actions advisories use ECOSYSTEM ranges OSV cannot match
// against a supplied version, so we fetch all of them and evaluate ranges locally.
func queryActionAdvisories(client *http.Client, name string) ([]osvVuln, error) {
	payload, err := json.Marshal(map[string]any{
		"package": osvPackage{Ecosystem: actionsEcosystem, Name: name},
	})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest(http.MethodPost, osvQueryURL, bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("osv.dev returned status %d", resp.StatusCode)
	}

	var out struct {
		Vulns []osvVuln `json:"vulns"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out.Vulns, nil
}

// --- GitHub tag resolution ---

// ghTag is a single entry from the GitHub list-tags API.
type ghTag struct {
	Name   string `json:"name"`
	Commit struct {
		SHA string `json:"sha"`
	} `json:"commit"`
}

// resolveActionTags lists the tags of an action's repo via the GitHub CLI, reusing
// the same authenticated `gh` the Dependabot audit relies on. Public-repo reads
// work with any token.
func resolveActionTags(name string) ([]ghTag, error) {
	// per_page goes in the query string, not as a -f field: gh switches to POST
	// when any -f/-F field is set without an explicit method, which 404s on this
	// GET-only endpoint.
	cmd := exec.Command("gh", "api",
		"repos/"+name+"/tags?per_page=100",
		"--paginate",
	)
	out, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("%w: %s", err, strings.TrimSpace(string(exitErr.Stderr)))
		}
		return nil, err
	}
	tags, err := parseTagPages(out)
	if err != nil {
		return nil, fmt.Errorf("failed to parse tags for %s: %w", name, err)
	}
	return tags, nil
}

// parseTagPages flattens the output of `gh api --paginate`. Depending on the gh
// version it emits either a single merged JSON array or one array per page
// (concatenated without a wrapper); decoding the stream of arrays handles both.
func parseTagPages(data []byte) ([]ghTag, error) {
	var tags []ghTag
	dec := json.NewDecoder(bytes.NewReader(data))
	for {
		var page []ghTag
		if err := dec.Decode(&page); err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			return nil, err
		}
		tags = append(tags, page...)
	}
	return tags, nil
}

// versionForSHA returns the highest semver tag whose commit matches sha. The bool
// is false when no semver tag points at the commit (e.g. a pin to an untagged
// commit), leaving the ref unresolvable.
func versionForSHA(tags []ghTag, sha string) (string, bool) {
	best := ""
	for _, t := range tags {
		if !strings.EqualFold(t.Commit.SHA, sha) {
			continue
		}
		v := version.Normalize(t.Name)
		if !version.IsSemverish(v) {
			continue
		}
		if best == "" || version.Compare(v, best) > 0 {
			best = v
		}
	}
	return best, best != ""
}

// --- Advisory range evaluation ---

// affectedByAdvisory reports whether a resolved version falls within any of the
// advisory's GitHub Actions affected ranges.
func affectedByAdvisory(ver string, v osvVuln) bool {
	for _, aff := range v.Affected {
		if !strings.EqualFold(aff.Package.Ecosystem, actionsEcosystem) {
			continue
		}
		for _, e := range aff.Versions {
			if version.Normalize(e) == ver {
				return true
			}
		}
		for _, r := range aff.Ranges {
			// GitHub advisories use ECOSYSTEM ranges; accept SEMVER too since both
			// carry semver-ordered bounds for this ecosystem.
			if r.Type != "ECOSYSTEM" && r.Type != "SEMVER" {
				continue
			}
			if inRange(ver, r.Events) {
				return true
			}
		}
	}
	return false
}

// rangeEvent is a flattened OSV range event.
type rangeEvent struct {
	kind string // introduced | fixed | last_affected
	ver  string
}

// inRange applies OSV range semantics: walking events in ascending version order,
// an "introduced" opens the affected interval and a "fixed"/"last_affected" closes
// it. target is affected if the interval is open once all events at or below it
// have been applied.
func inRange(target string, events []map[string]string) bool {
	var evs []rangeEvent
	for _, e := range events {
		for kind, ver := range e {
			evs = append(evs, rangeEvent{kind: kind, ver: ver})
		}
	}
	sort.SliceStable(evs, func(i, j int) bool {
		if evs[i].ver == evs[j].ver {
			return false
		}
		// "introduced: 0" is the lower bound and always sorts first.
		if evs[i].ver == "0" {
			return true
		}
		if evs[j].ver == "0" {
			return false
		}
		return version.Compare(evs[i].ver, evs[j].ver) < 0
	})

	affected := false
	for _, e := range evs {
		switch e.kind {
		case "introduced":
			if e.ver == "0" || version.Compare(target, e.ver) >= 0 {
				affected = true
			}
		case "fixed":
			if version.Compare(target, e.ver) >= 0 {
				affected = false
			}
		case "last_affected":
			if version.Compare(target, e.ver) > 0 {
				affected = false
			}
		}
	}
	return affected
}

// firstFixed returns the earliest "fixed" version across the advisory's GitHub
// Actions ranges, for display as the remediation target.
func firstFixed(v osvVuln) string {
	fixed := ""
	for _, aff := range v.Affected {
		if !strings.EqualFold(aff.Package.Ecosystem, actionsEcosystem) {
			continue
		}
		for _, r := range aff.Ranges {
			for _, e := range r.Events {
				if f, ok := e["fixed"]; ok && f != "" {
					if fixed == "" || version.Compare(f, fixed) < 0 {
						fixed = f
					}
				}
			}
		}
	}
	return fixed
}

// --- Finding construction ---

// actionFinding builds a Finding for an advisory affecting an action. When
// confirmed is false the pin could not be resolved to a comparable version, so the
// finding is demoted to unknown severity (non-blocking) and flagged as unverified.
func actionFinding(ref actionRef, v osvVuln, confirmed bool) Finding {
	f := Finding{
		ID:        v.ID,
		Aliases:   v.Aliases,
		Ecosystem: actionsEcosystem,
		Package:   ref.Name,
		Version:   ref.Ref,
		Severity:  actionSeverity(v),
		Title:     actionTitle(v),
		URL:       osvBaseURL + v.ID,
		Source:    SourceActions,
		FixedIn:   firstFixed(v),
		Manifest:  ref.Manifest,
	}
	if !confirmed {
		f.Severity = SeverityUnknown
		f.Title = "unverified pin — " + f.Title
	}
	return f
}

// actionSeverity reads the GHSA severity label from the advisory's
// database_specific block, mirroring the lockfile scanner's fallback path.
func actionSeverity(v osvVuln) Severity {
	if v.DatabaseSpecific != nil {
		if label, ok := v.DatabaseSpecific["severity"].(string); ok {
			if s := ParseSeverity(label); s != SeverityUnknown {
				return s
			}
		}
	}
	return SeverityUnknown
}

// actionTitle returns a one-line advisory title, preferring the summary.
func actionTitle(v osvVuln) string {
	if s := strings.TrimSpace(v.Summary); s != "" {
		return s
	}
	details := strings.TrimSpace(v.Details)
	if line, _, found := strings.Cut(details, "\n"); found {
		return strings.TrimSpace(line)
	}
	return details
}
