package audit

import (
	"cmp"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
)

// AlertLabel marks the tracking issue opened for each vulnerable package. The
// open issues are the alert state: one exists while the package is blocking.
const AlertLabel = "cve-alert"

// AlertPendingLabel marks an issue whose alert has not been announced yet. The
// workflow removes it after the Slack post, and every sync until then
// announces the alert again, so a failed run never loses one.
const AlertPendingLabel = "cve-alert-pending"

// alertIssueLimit caps the open issues a sync reads. A sync that hits it fails,
// since the unread issues' packages would get duplicate issues.
const alertIssueLimit = 500

// alertMarker is the hidden line ending a tracking issue body that ties it to
// a package and records the advisory ids it has already alerted on. Keys can
// hold spaces ("GitHub Actions/..."), so the key match is lazy.
var alertMarker = regexp.MustCompile(`<!-- cve-alert:(.+?) ids=(\S*) -->`)

// branchUnsafe matches runs of characters a fix branch name leaves out.
var branchUnsafe = regexp.MustCompile(`[^A-Za-z0-9._/-]+`)

// Advisory is one advisory affecting an alerted package.
type Advisory struct {
	ID       string   `json:"id"`
	Aliases  []string `json:"aliases,omitempty"`
	Severity Severity `json:"severity"`
	Title    string   `json:"title,omitempty"`
	URL      string   `json:"url,omitempty"`
	FixedIn  string   `json:"fixed_in,omitempty"`
	// lendsNames marks a record from a non-blocking finding, kept only while
	// grouping to carry its names into a blocking advisory.
	lendsNames bool
}

// AlertReason says why a sync announces an alert.
type AlertReason string

const (
	AlertNew   AlertReason = "new"
	AlertGrown AlertReason = "grown"
	AlertRetry AlertReason = "retry"
)

// Alert groups the blocking findings for one package, the unit that gets a
// tracking issue, a fix PR, and a Slack post.
type Alert struct {
	Key        string     `json:"key"`
	Ecosystem  string     `json:"ecosystem"`
	Package    string     `json:"package"`
	Advisories []Advisory `json:"advisories"`
	Versions   []string   `json:"versions,omitempty"`
	Manifests  []string   `json:"manifests,omitempty"`
	// Branch is where the workflow pushes the fix when Dependabot has no open
	// PR for the package, and whose PR a sync closes with the issue.
	Branch   string      `json:"branch"`
	Issue    int         `json:"issue,omitempty"`
	IssueURL string      `json:"issue_url,omitempty"`
	Reason   AlertReason `json:"reason,omitempty"`
}

// trackedIssue is an open tracking issue and the state it records.
type trackedIssue struct {
	Number  int
	URL     string
	Key     string
	IDs     []string
	Pending bool
}

// alertPlan is what a sync does to the open tracking issues.
type alertPlan struct {
	// Create holds alerts with no open issue, Update those with an advisory id
	// missing from their issue's marker, Retry those still pending
	// announcement. All three get announced.
	Create []Alert
	Update []Alert
	Retry  []Alert
	// Close holds issues whose package no longer blocks.
	Close []trackedIssue
}

// SyncAlertsOptions configures SyncAlerts.
type SyncAlertsOptions struct {
	// ResultFiles are JSON results written by `ods audit --format=json` or
	// `ods audit image --format=json`. Together they must cover every scan, or
	// the packages they omit have their issues closed.
	ResultFiles []string
	// IgnoreURL is the allowlist applied to the results. Unlike a scan, a sync
	// fails when it cannot fetch it, since every accepted advisory would
	// otherwise open an issue.
	IgnoreURL string
	DryRun    bool
}

// SyncAlerts keeps one open issue per package with an unsuppressed blocking
// finding, and returns the alerts to announce: new, grown, or still pending.
// After a failed issue change it still returns the alerts it could record,
// with the error.
func SyncAlerts(opts SyncAlertsOptions) ([]Alert, error) {
	var blocking, scanned []Finding
	for _, path := range opts.ResultFiles {
		res, err := readResult(path)
		if err != nil {
			return nil, err
		}
		blocking = append(blocking, res.Blocking...)
		scanned = append(scanned, res.Findings...)
		scanned = append(scanned, res.Ignored...)
	}
	ignores, err := FetchIgnores(opts.IgnoreURL)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch the allowlist from %s: %w", opts.IgnoreURL, err)
	}
	alerts := suppressAlerts(groupAlerts(blocking, scanned), ignores, time.Now())

	open, err := listAlertIssues()
	if err != nil {
		return nil, err
	}
	plan := planAlerts(alerts, open, coveredEcosystems(scanned))

	if opts.DryRun {
		logPlan(plan)
		return slices.Concat(plan.Create, plan.Update, plan.Retry), nil
	}
	return applyPlan(plan)
}

// suppressAlerts drops the advisories the allowlist covers, matching each by
// every id and alias its sources reported, and the alerts left with none.
func suppressAlerts(alerts []Alert, ignores []IgnoreEntry, now time.Time) []Alert {
	var kept []Alert
	for _, a := range alerts {
		a.Advisories = slices.DeleteFunc(a.Advisories, func(adv Advisory) bool {
			return matchIgnore(Finding{ID: adv.ID, Aliases: adv.Aliases, Ecosystem: a.Ecosystem}, ignores, now) != nil
		})
		if len(a.Advisories) > 0 {
			kept = append(kept, a)
		}
	}
	return kept
}

// coveredEcosystems lists the ecosystems the scans reported any finding in.
// Only there does a package's absence mean it was fixed, not that a partial
// extraction missed it.
func coveredEcosystems(findings []Finding) map[string]bool {
	covered := map[string]bool{}
	for _, f := range findings {
		covered[canonicalEcosystem(f.Ecosystem)] = true
	}
	return covered
}

// applyPlan makes the issue changes and returns the alerts to announce whose
// issue it opened, updated, or found pending. It keeps going past a failed
// change, since each one retries on the next sync.
func applyPlan(plan alertPlan) ([]Alert, error) {
	var announced []Alert
	var errs []error
	creates := plan.Create
	if len(creates)+len(plan.Update) > 0 {
		if err := ensureAlertLabels(); err != nil {
			errs = append(errs, err)
			creates, plan.Update = nil, nil
		}
	}
	for _, a := range creates {
		if err := createAlertIssue(&a); err != nil {
			errs = append(errs, err)
			continue
		}
		announced = append(announced, a)
	}
	for _, a := range plan.Update {
		// gh sends the label and the body as separate requests. Labelling first
		// means a failure can never leave the new advisory in the marker unmarked.
		if _, err := ghOutput("", "issue", "edit", strconv.Itoa(a.Issue), "--add-label", AlertPendingLabel); err != nil {
			errs = append(errs, fmt.Errorf("failed to mark issue #%d pending: %w", a.Issue, err))
			continue
		}
		if _, err := ghOutput(renderAlertBody(a), "issue", "edit", strconv.Itoa(a.Issue), "--body-file", "-"); err != nil {
			errs = append(errs, fmt.Errorf("failed to update issue #%d: %w", a.Issue, err))
			continue
		}
		log.Infof("Updated issue #%d for %s", a.Issue, a.Key)
		announced = append(announced, a)
	}
	announced = append(announced, plan.Retry...)
	for _, is := range plan.Close {
		if err := closeAlert(is); err != nil {
			errs = append(errs, err)
		}
	}
	return announced, errors.Join(errs...)
}

// closeAlert closes a resolved package's issue and the workflow's open fix PR
// for it. A PR pushed onto Dependabot's branch is left to Dependabot.
func closeAlert(is trackedIssue) error {
	comment := "This package no longer has a blocking finding: it was fixed or suppressed in the audit allowlist."
	out, err := ghOutput("", "pr", "list", "--state", "open", "--head", alertBranch(is.Key), "--json", "number", "--jq", ".[].number")
	if err != nil {
		return fmt.Errorf("failed to find the fix PR for %s: %w", is.Key, err)
	}
	for pr := range strings.FieldsSeq(out) {
		if _, err := ghOutput("", "pr", "close", pr, "--comment", comment); err != nil {
			return fmt.Errorf("failed to close fix PR #%s for %s: %w", pr, is.Key, err)
		}
		log.Infof("Closed fix PR #%s for %s", pr, is.Key)
	}
	if _, err := ghOutput("", "issue", "close", strconv.Itoa(is.Number), "--comment", comment); err != nil {
		return fmt.Errorf("failed to close issue #%d: %w", is.Number, err)
	}
	log.Infof("Closed issue #%d for %s", is.Number, is.Key)
	return nil
}

// alertBranch names the fix branch for an alert key such as "npm/@scope/pkg".
// The hash keeps keys that sanitize alike on separate branches.
func alertBranch(key string) string {
	sum := sha256.Sum256([]byte(key))
	return "cve-alerts/" + branchUnsafe.ReplaceAllString(strings.ReplaceAll(key, "@", ""), "-") + "-" + hex.EncodeToString(sum[:4])
}

func readResult(path string) (*Result, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var res Result
	if err := json.Unmarshal(data, &res); err != nil {
		return nil, fmt.Errorf("failed to parse audit result %s: %w", path, err)
	}
	return &res, nil
}

// groupAlerts folds blocking findings into one alert per package, merging an
// advisory's sources by id or alias. Scanned findings lend their names, so the
// allowlist also matches ids only a non-blocking source reported.
func groupAlerts(blocking, scanned []Finding) []Alert {
	byKey := map[string]*Alert{}
	var keys []string
	for _, f := range blocking {
		key := alertKey(f)
		a := byKey[key]
		if a == nil {
			eco := canonicalEcosystem(f.Ecosystem)
			a = &Alert{Key: key, Ecosystem: eco, Package: canonicalPackage(eco, f.Package), Branch: alertBranch(key)}
			byKey[key] = a
			keys = append(keys, key)
		}
		a.Advisories = append(a.Advisories, Advisory{
			ID:       f.ID,
			Aliases:  slices.Clone(f.Aliases),
			Severity: f.Severity,
			Title:    f.Title,
			URL:      f.URL,
			FixedIn:  f.FixedIn,
		})
		a.Versions = appendUnique(a.Versions, f.Version)
		a.Manifests = appendUnique(a.Manifests, f.Manifest)
	}
	for _, f := range scanned {
		if a := byKey[alertKey(f)]; a != nil {
			a.Advisories = append(a.Advisories, Advisory{ID: f.ID, Aliases: slices.Clone(f.Aliases), lendsNames: true})
		}
	}

	sort.Strings(keys)
	alerts := make([]Alert, 0, len(keys))
	for _, key := range keys {
		a := byKey[key]
		a.Advisories = mergeLinked(a.Advisories)
		sort.Strings(a.Versions)
		sort.Strings(a.Manifests)
		sort.Slice(a.Advisories, func(i, j int) bool { return a.Advisories[i].ID < a.Advisories[j].ID })
		alerts = append(alerts, *a)
	}
	return alerts
}

func alertKey(f Finding) string {
	eco := canonicalEcosystem(f.Ecosystem)
	return eco + "/" + canonicalPackage(eco, f.Package)
}

// pythonNameSeparators matches the runs PEP 503 folds into one "-".
var pythonNameSeparators = regexp.MustCompile(`[-_.]+`)

// canonicalPackage spells a package name one way per ecosystem, so "Pillow"
// and "pillow" from different sources land in one alert.
func canonicalPackage(ecosystem, name string) string {
	if ecosystem != "PyPI" {
		return name
	}
	return pythonNameSeparators.ReplaceAllString(strings.ToLower(name), "-")
}

// mergeLinked joins advisories that share any id or alias, transitively, and
// drops the name-lending records no blocking advisory joined.
func mergeLinked(advs []Advisory) []Advisory {
	for i := 0; i < len(advs); i++ {
		for j := i + 1; j < len(advs); j++ {
			if !shareName(advs[i], advs[j]) {
				continue
			}
			advs[i] = unionAdvisory(advs[i], advs[j])
			advs = slices.Delete(advs, j, j+1)
			// advs[i] gained names, so rescan everything after it.
			j = i
		}
	}
	return slices.DeleteFunc(advs, func(adv Advisory) bool { return adv.lendsNames })
}

func advisoryNames(adv Advisory) []string {
	return append([]string{adv.ID}, adv.Aliases...)
}

func shareName(a, b Advisory) bool {
	return slices.ContainsFunc(advisoryNames(a), func(n string) bool {
		return slices.ContainsFunc(advisoryNames(b), func(m string) bool { return strings.EqualFold(n, m) })
	})
}

// unionAdvisory folds b into a. A blocking advisory keeps its id and fields
// over a name-lending one.
func unionAdvisory(a, b Advisory) Advisory {
	if a.lendsNames && !b.lendsNames {
		a, b = b, a
	}
	for _, n := range advisoryNames(b) {
		if !strings.EqualFold(n, a.ID) {
			a.Aliases = appendUnique(a.Aliases, n)
		}
	}
	a.Title = cmp.Or(a.Title, b.Title)
	a.URL = cmp.Or(a.URL, b.URL)
	a.FixedIn = cmp.Or(a.FixedIn, b.FixedIn)
	return a
}

// planAlerts decides the issue changes that bring the open issues in line with
// the current alerts. An issue closes only when its ecosystem is covered.
func planAlerts(alerts []Alert, open []trackedIssue, covered map[string]bool) alertPlan {
	byKey := make(map[string]trackedIssue, len(open))
	for _, is := range open {
		byKey[is.Key] = is
	}

	var plan alertPlan
	seen := map[string]bool{}
	for _, a := range alerts {
		seen[a.Key] = true
		is, ok := byKey[a.Key]
		if !ok {
			a.Reason = AlertNew
			plan.Create = append(plan.Create, a)
			continue
		}
		a.Issue, a.IssueURL = is.Number, is.URL
		switch {
		case hasNewAdvisory(a, is.IDs):
			a.Reason = AlertGrown
			plan.Update = append(plan.Update, a)
		case is.Pending:
			a.Reason = AlertRetry
			plan.Retry = append(plan.Retry, a)
		}
	}
	for _, is := range open {
		if seen[is.Key] {
			continue
		}
		if eco, _, _ := strings.Cut(is.Key, "/"); !covered[eco] {
			log.Warnf("Keeping issue #%d for %s open: no scan reported any %s finding", is.Number, is.Key, eco)
			continue
		}
		plan.Close = append(plan.Close, is)
	}
	return plan
}

// hasNewAdvisory reports whether a has an advisory the issue has not alerted
// on under its id or any alias, since sources pick different representative ids.
func hasNewAdvisory(a Alert, alerted []string) bool {
	for _, adv := range a.Advisories {
		known := slices.ContainsFunc(advisoryNames(adv), func(name string) bool {
			return slices.ContainsFunc(alerted, func(id string) bool { return strings.EqualFold(id, name) })
		})
		if !known {
			return true
		}
	}
	return false
}

// markerIDs lists every id and alias of a's advisories for the issue marker.
func markerIDs(a Alert) string {
	var names []string
	for _, adv := range a.Advisories {
		names = appendUnique(names, advisoryNames(adv)...)
	}
	return strings.Join(names, ",")
}

func logPlan(plan alertPlan) {
	for _, a := range plan.Create {
		log.Infof("[dry run] would open an issue for %s (%s)", a.Key, advisoryIDs(a))
	}
	for _, a := range plan.Update {
		log.Infof("[dry run] would update issue #%d for %s (%s)", a.Issue, a.Key, advisoryIDs(a))
	}
	for _, a := range plan.Retry {
		log.Infof("[dry run] would announce pending issue #%d for %s again", a.Issue, a.Key)
	}
	for _, is := range plan.Close {
		log.Infof("[dry run] would close issue #%d for %s", is.Number, is.Key)
	}
}

func advisoryIDs(a Alert) string {
	ids := make([]string, 0, len(a.Advisories))
	for _, adv := range a.Advisories {
		ids = append(ids, adv.ID)
	}
	return strings.Join(ids, ",")
}

// renderAlertBody renders the tracking issue body, ending with the marker that
// ties the issue to its package.
func renderAlertBody(a Alert) string {
	var b strings.Builder
	fmt.Fprintf(&b, "`%s` (%s) has a blocking vulnerability.\n\n", a.Package, a.Ecosystem)
	b.WriteString("| Advisory | Severity | Fixed in | Summary |\n|---|---|---|---|\n")
	for _, adv := range a.Advisories {
		id := adv.ID
		if adv.URL != "" {
			id = fmt.Sprintf("[%s](%s)", adv.ID, adv.URL)
		}
		fmt.Fprintf(&b, "| %s | %s | %s | %s |\n", id, adv.Severity, orDash(adv.FixedIn), tableCell(adv.Title))
	}
	if len(a.Versions) > 0 {
		fmt.Fprintf(&b, "\n**Installed:** %s\n", strings.Join(a.Versions, ", "))
	}
	if len(a.Manifests) > 0 {
		fmt.Fprintf(&b, "\n**Found in:**\n")
		for _, m := range a.Manifests {
			fmt.Fprintf(&b, "- `%s`\n", m)
		}
	}
	b.WriteString("\nThis issue closes by itself once the finding is fixed or suppressed in the audit allowlist.\n\n")
	fmt.Fprintf(&b, "<!-- cve-alert:%s ids=%s -->\n", a.Key, markerIDs(a))
	return b.String()
}

// tableCell fits advisory text into a table cell. Escaping "<" keeps the text
// from opening an HTML comment that could pose as the marker.
func tableCell(s string) string {
	return orDash(strings.NewReplacer("|", `\|`, "\n", " ", "<", "&lt;").Replace(s))
}

func orDash(s string) string {
	if s == "" {
		return "-"
	}
	return s
}

// parseTrackedIssue reads the last marker from an issue body, the one the sync
// wrote. ok is false for an issue with the label but no marker, which a sync
// leaves alone.
func parseTrackedIssue(number int, url, body string, pending bool) (trackedIssue, bool) {
	all := alertMarker.FindAllStringSubmatch(body, -1)
	if len(all) == 0 {
		return trackedIssue{}, false
	}
	m := all[len(all)-1]
	is := trackedIssue{Number: number, URL: url, Key: m[1], Pending: pending}
	if m[2] != "" {
		is.IDs = strings.Split(m[2], ",")
	}
	return is, true
}

func listAlertIssues() ([]trackedIssue, error) {
	out, err := ghOutput("", "issue", "list",
		"--label", AlertLabel,
		"--state", "open",
		"--limit", strconv.Itoa(alertIssueLimit),
		"--json", "number,url,body,labels",
	)
	if err != nil {
		return nil, fmt.Errorf("failed to list %s issues: %w", AlertLabel, err)
	}
	type ghLabel struct {
		Name string `json:"name"`
	}
	var raw []struct {
		Number int       `json:"number"`
		URL    string    `json:"url"`
		Body   string    `json:"body"`
		Labels []ghLabel `json:"labels"`
	}
	if err := json.Unmarshal([]byte(out), &raw); err != nil {
		return nil, fmt.Errorf("failed to parse %s issues: %w", AlertLabel, err)
	}
	if len(raw) >= alertIssueLimit {
		return nil, fmt.Errorf("found %d open %s issues, the most a sync reads; close stale ones first", len(raw), AlertLabel)
	}
	issues := make([]trackedIssue, 0, len(raw))
	for _, r := range raw {
		pending := slices.ContainsFunc(r.Labels, func(l ghLabel) bool { return l.Name == AlertPendingLabel })
		is, ok := parseTrackedIssue(r.Number, r.URL, r.Body, pending)
		if !ok {
			log.Warnf("Issue #%d has the %s label but no marker; leaving it alone", r.Number, AlertLabel)
			continue
		}
		issues = append(issues, is)
	}
	return issues, nil
}

func ensureAlertLabels() error {
	for _, l := range []struct{ name, description string }{
		{AlertLabel, "Tracks a blocking dependency vulnerability; opened and closed by the CVE alerts workflow"},
		{AlertPendingLabel, "The CVE alerts workflow has not announced this alert yet"},
	} {
		if _, err := ghOutput("", "label", "create", l.name, "--color", "B60205", "--description", l.description, "--force"); err != nil {
			return fmt.Errorf("failed to create the %s label: %w", l.name, err)
		}
	}
	return nil
}

func createAlertIssue(a *Alert) error {
	title := fmt.Sprintf("Vulnerable dependency: %s (%s)", a.Package, a.Ecosystem)
	out, err := ghOutput(renderAlertBody(*a), "issue", "create",
		"--title", title,
		"--label", AlertLabel,
		"--label", AlertPendingLabel,
		"--body-file", "-",
	)
	if err != nil {
		return fmt.Errorf("failed to open an issue for %s: %w", a.Key, err)
	}
	// gh prints the new issue's URL, which ends in its number.
	a.IssueURL = strings.TrimSpace(out)
	n, err := strconv.Atoi(path.Base(a.IssueURL))
	if err != nil {
		return fmt.Errorf("unexpected gh issue create output %q", a.IssueURL)
	}
	a.Issue = n
	log.Infof("Opened issue #%d for %s", a.Issue, a.Key)
	return nil
}

// ghOutput runs a gh command, feeding stdin when it is non-empty, and folds
// gh's stderr into the error since it holds the useful message.
func ghOutput(stdin string, args ...string) (string, error) {
	cmd := exec.Command("gh", args...)
	if stdin != "" {
		cmd.Stdin = strings.NewReader(stdin)
	}
	out, err := cmd.Output()
	if exitErr, ok := err.(*exec.ExitError); ok {
		return "", fmt.Errorf("%w: %s", err, strings.TrimSpace(string(exitErr.Stderr)))
	}
	return string(out), err
}

func appendUnique(list []string, values ...string) []string {
	for _, v := range values {
		if v != "" && !slices.Contains(list, v) {
			list = append(list, v)
		}
	}
	return list
}
