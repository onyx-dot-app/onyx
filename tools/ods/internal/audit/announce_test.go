package audit

import (
	"fmt"
	"strings"
	"testing"
)

func chromiumAlert() Alert {
	return Alert{
		Key: "Debian:13/chromium", Ecosystem: "Debian:13", Package: "chromium",
		Versions: []string{"155.0.8059.39-1~deb13u1"}, Issue: 16065, IssueURL: "https://github.com/o/r/issues/16065",
		Advisories: []Advisory{
			{ID: "DEBIAN-CVE-2026-110136", Aliases: []string{"CVE-2026-110136"}, URL: "https://osv.dev/DEBIAN-CVE-2026-110136", Images: []string{"sandbox"}},
			{ID: "DEBIAN-CVE-2026-110142", URL: "https://osv.dev/DEBIAN-CVE-2026-110142", Images: []string{"sandbox"}},
			{ID: "DEBIAN-CVE-2026-110149", Images: []string{"sandbox"}},
		},
	}
}

func baseAnnounce() AnnounceOptions {
	return AnnounceOptions{
		Branch: "main", RunURL: "https://run/1", Owner: "<@U1>", Expires: "2026-11-14",
		Triage: map[int]TriageSummary{16065: {Issue: 16065, Fix: "*Fix PR:* none.", Verdict: "affected", Note: "a <script> & more", Reason: `no "fix" $yet`}},
	}
}

func TestPlanAnnouncement_postsEveryNewAdvisoryOnceWithItsImageAndCommand(t *testing.T) {
	opts := baseAnnounce()
	glibc := Alert{Key: "Debian:13/glibc", Ecosystem: "Debian:13", Package: "glibc", Issue: 7, IssueURL: "https://i/7",
		Advisories: []Advisory{{ID: "CVE-2026-1", Images: []string{"backend", "sandbox"}}}}
	opts.Failing = []Alert{chromiumAlert(), glibc}
	plan := PlanAnnouncement(opts)

	if plan.Post == nil {
		t.Fatal("no post")
	}
	text := plan.Post.Text
	for _, want := range []string{"*🚨 Audit failed on main: 4 critical CVEs* <@U1>", "<https://osv.dev/DEBIAN-CVE-2026-110136|DEBIAN-CVE-2026-110136> in *sandbox*", "`DEBIAN-CVE-2026-110149` in *sandbox*", "`CVE-2026-1` in *backend, sandbox*: glibc", "<https://i/7|#7>", "*Run:* <https://run/1|CVE Alerts run>"} {
		if !strings.Contains(text, want) {
			t.Errorf("post missing %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "*Audit:*") {
		t.Errorf("post links an audit run it was not given:\n%s", text)
	}
	if len(plan.Post.Thread) != 2 {
		t.Fatalf("want one thread reply per package, got %d", len(plan.Post.Thread))
	}
	chromium := plan.Post.Thread[0]
	for _, id := range []string{"110136", "110142", "110149"} {
		if n := strings.Count(chromium, "ods audit ignore add DEBIAN-CVE-2026-"+id); n != 2 {
			t.Errorf("want 2 ignore commands for %s, got %d:\n%s", id, n, chromium)
		}
	}
	for _, want := range []string{"*Fix PR:* none.", "Verdict affected. a &lt;script&gt; &amp; more", `--reason "no 'fix' yet" --expires 2026-11-14`} {
		if !strings.Contains(chromium, want) {
			t.Errorf("chromium reply missing %q:\n%s", want, chromium)
		}
	}
	if !strings.Contains(plan.Post.Thread[1], "not triaged in this run") || !strings.Contains(plan.Post.Thread[1], "&lt;why this is not exploitable in Onyx&gt;") {
		t.Errorf("untriaged package reply:\n%s", plan.Post.Thread[1])
	}
	if len(plan.Markers) != 2 || plan.Markers[0].Issue != 16065 || strings.Join(plan.Markers[0].IDs, ",") != "DEBIAN-CVE-2026-110136,CVE-2026-110136,DEBIAN-CVE-2026-110142,DEBIAN-CVE-2026-110149" {
		t.Errorf("markers: %+v", plan.Markers)
	}
	if len(plan.Replies) != 0 {
		t.Errorf("unexpected replies: %+v", plan.Replies)
	}
	if len(plan.Issues) != 1 || plan.Issues[0] != 16065 {
		t.Errorf("announced issues: %v, want only the triaged one", plan.Issues)
	}
}

func TestPlanAnnouncement_threadsRepeatsAndPostsOnlyNewAdvisories(t *testing.T) {
	opts := baseAnnounce()
	opts.AuditURL = "https://audit/9"
	opts.Failing = []Alert{chromiumAlert()}
	// Matched by alias and case-insensitively; two threads from two earlier runs.
	opts.Threads = map[string]string{"cve-2026-110136": "111.1", "DEBIAN-CVE-2026-110142": "222.2"}
	plan := PlanAnnouncement(opts)

	if plan.Post == nil || !strings.Contains(plan.Post.Text, "1 critical CVE*") || !strings.Contains(plan.Post.Text, "*Audit:* <https://audit/9|failed run>") {
		t.Fatalf("post: %+v", plan.Post)
	}
	if strings.Contains(plan.Post.Text, "110136") || strings.Contains(plan.Post.Thread[0], "110142") {
		t.Errorf("repeat advisory in the new post: %+v", plan.Post)
	}
	if len(plan.Replies) != 2 {
		t.Fatalf("want a reply per thread, got %+v", plan.Replies)
	}
	if plan.Replies[0].TS != "111.1" || plan.Replies[0].Text != "*DEBIAN-CVE-2026-110136* also failed on this run: <https://audit/9|run> (sandbox, main)" {
		t.Errorf("reply: %+v", plan.Replies[0])
	}
	if len(plan.Markers) != 1 || strings.Join(plan.Markers[0].IDs, ",") != "DEBIAN-CVE-2026-110149" {
		t.Errorf("markers: %+v", plan.Markers)
	}
}

func TestPlanAnnouncement_allRepeatsPostNothingNewAndCarryARetriedTriage(t *testing.T) {
	opts := baseAnnounce()
	opts.Failing = []Alert{chromiumAlert()}
	opts.Threads = map[string]string{"DEBIAN-CVE-2026-110136": "111.1", "DEBIAN-CVE-2026-110142": "111.1", "DEBIAN-CVE-2026-110149": "111.1"}
	plan := PlanAnnouncement(opts)

	if plan.Post != nil || len(plan.Markers) != 0 {
		t.Fatalf("want no new post: %+v", plan)
	}
	if len(plan.Replies) != 2 || plan.Replies[0].TS != "111.1" || plan.Replies[1].TS != "111.1" {
		t.Fatalf("replies: %+v", plan.Replies)
	}
	if strings.Count(plan.Replies[0].Text, "also failed on this run") != 3 || !strings.Contains(plan.Replies[1].Text, "Verdict affected") {
		t.Errorf("replies: %+v", plan.Replies)
	}
	if len(plan.Issues) != 1 {
		t.Errorf("a retried triage is announced in its thread: %v", plan.Issues)
	}

	opts.Triage = nil
	if plan := PlanAnnouncement(opts); len(plan.Issues) != 0 || len(plan.Replies) != 1 || strings.Contains(plan.Replies[0].Text, "Verdict") {
		t.Errorf("untriaged repeats: %+v", plan)
	}
}

func TestPlanAnnouncement_retriedPackagesSplitBelowSlackSplitSize(t *testing.T) {
	opts := baseAnnounce()
	opts.Threads = map[string]string{}
	var curlAdvs []Advisory
	for i := range 12 {
		id := fmt.Sprintf("DEBIAN-CVE-2026-%d", 9000+i)
		curlAdvs = append(curlAdvs, Advisory{ID: id, Images: []string{"sandbox"}})
		opts.Threads[id] = "111.1"
	}
	curl := Alert{Key: "Debian:13/curl", Ecosystem: "Debian:13", Package: "curl", Issue: 17, IssueURL: "https://i/17", Advisories: curlAdvs}
	chromium := chromiumAlert()
	for _, adv := range chromium.Advisories {
		opts.Threads[adv.ID] = "111.1"
	}
	opts.Failing = []Alert{chromium, curl}
	long := strings.Repeat("n", noteLimit)
	opts.Triage = map[int]TriageSummary{
		16065: {Issue: 16065, Fix: "*Fix PR:* none.", Verdict: "affected", Note: long, Reason: strings.Repeat("r", 200)},
		17:    {Issue: 17, Fix: "*Fix PR:* none.", Verdict: "not_affected", Note: long, Reason: strings.Repeat("r", 200)},
	}
	plan := PlanAnnouncement(opts)

	var all []string
	for i, r := range plan.Replies {
		if r.TS != "111.1" {
			t.Errorf("reply %d went to thread %q", i, r.TS)
		}
		if n := runeLen(r.Text); n > slackMessageLimit {
			t.Errorf("reply %d has %d characters, past the limit", i, n)
		}
		if strings.Count(r.Text, "```")%2 != 0 {
			t.Errorf("reply %d leaves a code block open:\n%s", i, r.Text)
		}
		all = append(all, r.Text)
	}
	text := strings.Join(all, "\n")
	if c, u := strings.Index(text, "*chromium (Debian:13)*"), strings.Index(text, "*curl (Debian:13)*"); c < 0 || u < c {
		t.Errorf("want chromium's section, then curl's: chromium at %d, curl at %d", c, u)
	}
	for _, adv := range append(chromium.Advisories, curlAdvs...) {
		if got := strings.Count(text, "ods audit ignore add "+adv.ID+" "); got != 2 {
			t.Errorf("%s has %d ignore commands, want 2", adv.ID, got)
		}
	}
}

func TestPackageSection_fitsOneMessageWhenSmall(t *testing.T) {
	opts := baseAnnounce()
	a := chromiumAlert()
	if msgs := packageSection(a, a.Advisories, opts.Triage[16065], true, opts); len(msgs) != 1 {
		t.Errorf("want one message, got %d", len(msgs))
	}
}

func TestPlanAnnouncement_nothingFailingPostsNothing(t *testing.T) {
	plan := PlanAnnouncement(baseAnnounce())
	if plan.Post != nil || len(plan.Replies) != 0 || len(plan.Markers) != 0 {
		t.Errorf("plan: %+v", plan)
	}
}

func TestImageLabel_namesLockfilesWithoutAnImage(t *testing.T) {
	if got := imageLabel(nil); got != "lockfiles" {
		t.Errorf("got %q", got)
	}
}

func TestAnnounceHelpers(t *testing.T) {
	if got := truncateRunes("héllo", 2); got != "hé" {
		t.Errorf("truncateRunes: got %q", got)
	}
	if got := issueLink(Alert{Issue: 3}); got != "" {
		t.Errorf("issueLink without a URL: got %q", got)
	}
	if got := ignoreReason(" \n "); got != "&lt;why this is not exploitable in Onyx&gt;" {
		t.Errorf("ignoreReason of blank: got %q", got)
	}
	if got := ignoreReason(strings.Repeat("a", 130)); len(got) != 120 {
		t.Errorf("ignoreReason should cap at 120 runes, got %d", len(got))
	}
}

func TestCVECountNamesTheSeverities(t *testing.T) {
	cases := []struct {
		count      int
		severities map[Severity]int
		want       string
	}{
		{1, map[Severity]int{SeverityCritical: 1}, "1 critical CVE"},
		{4, map[Severity]int{SeverityCritical: 4}, "4 critical CVEs"},
		{18, map[Severity]int{SeverityHigh: 18}, "18 high CVEs"},
		{3, map[Severity]int{SeverityCritical: 1, SeverityHigh: 2}, "3 CVEs (1 critical, 2 high)"},
	}
	for _, tc := range cases {
		if got := cveCount(tc.count, tc.severities); got != tc.want {
			t.Errorf("cveCount(%d, %v) = %q, want %q", tc.count, tc.severities, got, tc.want)
		}
	}
}
