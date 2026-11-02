package audit

import (
	"cmp"
	"fmt"
	"sort"
	"strings"
)

// TriageSummary is what a publish job learned about one alerted package: the
// Slack line naming its fix and Claude's verdict, note, and ignore reason.
type TriageSummary struct {
	Issue   int    `json:"issue"`
	Fix     string `json:"fix"`
	Verdict string `json:"verdict,omitempty"`
	Note    string `json:"note,omitempty"`
	Reason  string `json:"reason,omitempty"`
}

// AnnounceOptions configures PlanAnnouncement.
type AnnounceOptions struct {
	// Failing holds every alert with a blocking finding in the run.
	Failing []Alert
	// Triage holds this run's triage of the announced alerts, by issue.
	Triage map[int]TriageSummary
	// Threads maps an advisory id or alias to the Slack post it was announced
	// in. Lookups ignore case.
	Threads map[string]string
	Branch  string
	// RunURL is this CVE Alerts run. AuditURL is the failed audit run that
	// dispatched it, if any; follow-ups link to it over RunURL.
	RunURL   string
	AuditURL string
	// Owner is the Slack mention of the reviewer who owns the whole run.
	Owner string
	// Expires is the date drafted into the temporary ignore commands.
	Expires string
}

// AnnouncePlan is what a run posts to Slack.
type AnnouncePlan struct {
	// Post is the run's top-level post, for advisories with no thread yet.
	Post *SlackPost `json:"post,omitempty"`
	// Markers lists, per issue, the advisory names the post announces, so a
	// later run threads them under it.
	Markers []ThreadMarker `json:"markers"`
	// Replies go in the threads of advisories announced by an earlier run,
	// split so no message passes Slack's split size.
	Replies []SlackReply `json:"replies"`
	// Issues lists the issues the plan announces, in the post or a reply.
	Issues []int `json:"issues"`
}

// SlackPost is a top-level message and the replies that go in its thread.
type SlackPost struct {
	Text   string   `json:"text"`
	Thread []string `json:"thread"`
}

// ThreadMarker ties an issue's advisory names to the run's post.
type ThreadMarker struct {
	Issue int      `json:"issue"`
	IDs   []string `json:"ids"`
}

// SlackReply is a message in an existing thread.
type SlackReply struct {
	TS   string `json:"ts"`
	Text string `json:"text"`
}

// noteLimit caps Claude's note per package, so the note and the package
// header fit in one message.
const noteLimit = 2500

// slackMessageLimit keeps each message below the ~4,000 characters past
// which Slack splits it, even mid code block.
const slackMessageLimit = 3800

// PlanAnnouncement splits a run's failing advisories into those announced
// before, which get a follow-up in their thread, and new ones, which all go
// in one top-level post owned by one reviewer.
func PlanAnnouncement(opts AnnounceOptions) AnnouncePlan {
	threads := make(map[string]string, len(opts.Threads))
	for name, ts := range opts.Threads {
		threads[strings.ToUpper(name)] = ts
	}
	link := opts.RunURL
	if opts.AuditURL != "" {
		link = opts.AuditURL
	}

	plan := AnnouncePlan{Markers: []ThreadMarker{}, Replies: []SlackReply{}, Issues: []int{}}
	var lines, sections []string
	repeats := map[string][]string{}
	retried := map[string][]string{}
	announced := map[int]bool{}
	count := 0
	for _, a := range opts.Failing {
		var fresh []Advisory
		firstTS := ""
		for _, adv := range a.Advisories {
			ts := threadOf(adv, threads)
			if ts == "" {
				fresh = append(fresh, adv)
				continue
			}
			firstTS = cmp.Or(firstTS, ts)
			repeats[ts] = append(repeats[ts], fmt.Sprintf("*%s* also failed on this run: <%s|run> (%s, %s)",
				adv.ID, link, imageLabel(adv.Images), opts.Branch))
		}
		triage, triaged := opts.Triage[a.Issue]
		if len(fresh) == 0 {
			// A retried triage has no new advisory, so its result goes in the
			// thread the package was announced in.
			if triaged && a.Issue > 0 {
				retried[firstTS] = append(retried[firstTS], packageSection(a, a.Advisories, triage, true, opts)...)
				announced[a.Issue] = true
			}
			continue
		}
		count += len(fresh)
		for _, adv := range fresh {
			lines = append(lines, fmt.Sprintf("• %s in *%s*: %s (%s) %s%s", advisoryLink(adv), imageLabel(adv.Images),
				a.Package, a.Ecosystem, versionLabel(a.Versions), issueLink(a)))
		}
		sections = append(sections, packageSection(a, fresh, triage, triaged, opts)...)
		if a.Issue > 0 {
			var ids []string
			for _, adv := range fresh {
				ids = appendUnique(ids, advisoryNames(adv)...)
			}
			plan.Markers = append(plan.Markers, ThreadMarker{Issue: a.Issue, IDs: ids})
			if triaged {
				announced[a.Issue] = true
			}
		}
	}

	if count > 0 {
		noun := "critical CVEs"
		if count == 1 {
			noun = "critical CVE"
		}
		text := []string{fmt.Sprintf("*🚨 Audit failed on %s: %d %s* %s", opts.Branch, count, noun, opts.Owner)}
		if opts.AuditURL != "" {
			text = append(text, fmt.Sprintf("*Audit:* <%s|failed run>", opts.AuditURL))
		}
		text = append(text, lines...)
		text = append(text, fmt.Sprintf("*Run:* <%s|CVE Alerts run>", opts.RunURL))
		plan.Post = &SlackPost{Text: strings.Join(text, "\n"), Thread: sections}
	}

	tss := make([]string, 0, len(repeats))
	for ts := range repeats {
		tss = append(tss, ts)
	}
	sort.Strings(tss)
	for _, ts := range tss {
		plan.Replies = append(plan.Replies, SlackReply{TS: ts, Text: strings.Join(repeats[ts], "\n")})
		for _, section := range retried[ts] {
			plan.Replies = append(plan.Replies, SlackReply{TS: ts, Text: section})
		}
	}
	for issue := range announced {
		plan.Issues = append(plan.Issues, issue)
	}
	sort.Ints(plan.Issues)
	return plan
}

func threadOf(adv Advisory, threads map[string]string) string {
	for _, name := range advisoryNames(adv) {
		if ts := threads[strings.ToUpper(name)]; ts != "" {
			return ts
		}
	}
	return ""
}

// packageSection is the thread reply for one package: its fix, Claude's
// note, and an ignore command for every advisory listed. It is one message
// unless it passes slackMessageLimit; then it splits between whole lines,
// and each message closes every code block it opens.
func packageSection(a Alert, advs []Advisory, triage TriageSummary, triaged bool, opts AnnounceOptions) []string {
	images := map[string]bool{}
	var imgs []string
	for _, adv := range advs {
		for _, img := range adv.Images {
			if !images[img] {
				images[img] = true
				imgs = append(imgs, img)
			}
		}
	}
	sort.Strings(imgs)
	var b strings.Builder
	fmt.Fprintf(&b, "*%s (%s)* in %s%s\n", a.Package, a.Ecosystem, imageLabel(imgs), issueLink(a))
	if !triaged {
		b.WriteString("*Fix PR:* not triaged in this run. See the tracking issue.\n")
	} else {
		if triage.Fix != "" {
			b.WriteString(triage.Fix + "\n")
		}
		if triage.Verdict != "" || triage.Note != "" {
			fmt.Fprintf(&b, "*Description:* Verdict %s. %s\n", slackEscape(triage.Verdict), truncateRunes(slackEscape(triage.Note), noteLimit))
		}
	}
	fmt.Fprintf(&b, "*Installed:* %s\n", truncateRunes(strings.Join(a.Versions, ", "), 200))
	reason := ignoreReason(triage.Reason)
	var ignores, expiring []string
	for _, adv := range advs {
		ignores = append(ignores, fmt.Sprintf("ods audit ignore add %s --reason \"%s\"", adv.ID, reason))
		expiring = append(expiring, fmt.Sprintf("ods audit ignore add %s --reason \"%s\" --expires %s", adv.ID, reason, opts.Expires))
	}
	units := []string{strings.TrimSuffix(b.String(), "\n")}
	units = append(units, commandBlocks("If Onyx is not affected, suppress it:", ignores)...)
	units = append(units, commandBlocks("If Onyx is affected and no fix exists yet, suppress it for 30 days:", expiring)...)
	return packMessages(units)
}

// commandBlocks puts the commands in as few code blocks as fit in a
// message each; the intro heads the first block.
func commandBlocks(intro string, cmds []string) []string {
	var blocks, chunk []string
	head := intro + "\n"
	flush := func() {
		if len(chunk) > 0 {
			blocks = append(blocks, head+"```\n"+strings.Join(chunk, "\n")+"\n```")
			head, chunk = "", nil
		}
	}
	size := 0
	for _, cmd := range cmds {
		// The fences and the intro take the rest of the budget.
		if size+runeLen(cmd)+1 > slackMessageLimit-runeLen(intro)-10 {
			flush()
			size = 0
		}
		chunk = append(chunk, cmd)
		size += runeLen(cmd) + 1
	}
	flush()
	return blocks
}

// packMessages joins units with newlines into as few messages as stay
// within slackMessageLimit. A unit is never split.
func packMessages(units []string) []string {
	var msgs []string
	cur := ""
	for _, u := range units {
		if cur != "" && runeLen(cur)+1+runeLen(u) > slackMessageLimit {
			msgs = append(msgs, cur)
			cur = ""
		}
		if cur == "" {
			cur = u
		} else {
			cur += "\n" + u
		}
	}
	return append(msgs, cur)
}

func runeLen(s string) int {
	return len([]rune(s))
}

// ignoreReason keeps Claude's reason a plain double-quoted shell string that
// cannot link or ping in Slack. `ods audit ignore add` rejects an empty one.
func ignoreReason(reason string) string {
	reason = strings.Map(func(r rune) rune {
		switch r {
		case '"':
			return '\''
		case '\t', '\r', '\n':
			return ' '
		case '`', '$', '\\':
			return -1
		}
		return r
	}, reason)
	reason = slackEscape(truncateRunes(strings.TrimSpace(reason), 120))
	if reason == "" {
		return "&lt;why this is not exploitable in Onyx&gt;"
	}
	return reason
}

func slackEscape(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;").Replace(s)
}

func truncateRunes(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

func imageLabel(images []string) string {
	if len(images) == 0 {
		return "lockfiles"
	}
	return strings.Join(images, ", ")
}

func versionLabel(versions []string) string {
	if len(versions) == 0 {
		return ""
	}
	return truncateRunes(strings.Join(versions, ", "), 200)
}

func advisoryLink(adv Advisory) string {
	if adv.URL == "" {
		return "`" + adv.ID + "`"
	}
	return fmt.Sprintf("<%s|%s>", adv.URL, adv.ID)
}

func issueLink(a Alert) string {
	if a.IssueURL == "" {
		return ""
	}
	return fmt.Sprintf(" <%s|#%d>", a.IssueURL, a.Issue)
}
