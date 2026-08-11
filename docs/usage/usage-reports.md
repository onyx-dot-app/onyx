# Usage reports: what they are for

This document defines what an Onyx usage report must tell an organization admin,
and why. It starts from the admin's job, not from the data we happen to store.

The rule that governs every decision here: **a number belongs in the report only
if the admin can finish the sentence "so I will...".** If no action follows, cut
the number.

## Where we are today

`create_new_usage_report` builds a zip with three CSVs and a PDF review pack:

| File                 | Contents                                                                              |
| -------------------- | ------------------------------------------------------------------------------------- |
| `chat_messages.csv`  | One row per message: session, user, flow, time, agent, email, tokens, model            |
| `users.csv`          | `user_id`, `is_active`                                                                  |
| `usage_by_user.csv`  | Per user, per day, per model/flow/provider: tokens, cache reads, cost                   |
| `usage_report.pdf`   | Summary of spend, adoption, seats, and usage attribution                                |

The raw CSV files are still a data dump. They have three problems:

1. **It answers no question.** The admin must build every pivot.
2. **It has no dimensions the admin budgets by.** No team, no agent, no source.
3. **It joins badly.** `users.csv` has no email, so it cannot join to the other files.

The raw export is still valuable. It is just the wrong artifact for every job.

## The admin's job

An org admin is accountable for three things:

1. **Money.** They signed the contract. They own the spend.
2. **Adoption.** They championed the rollout. Someone will ask if it worked.
3. **Risk.** If the tool leaks or misbehaves, it lands on them.

Every useful metric comes from one of these. The sections below derive the
metrics from the decisions.

### Decision: how many seats do I buy at renewal?

The admin needs a seat ledger, not a message count.

- Licensed seats, provisioned seats, and active seats.
- A named list of users who hold a seat and did not use it in 30 days.
- The inverse list: users who hit rate limits.

The named lists are the deliverable. The admin acts on them directly. They
reclaim a seat, retrain the person, or drop the seat at renewal.

### Decision: am I overspending, and what can I cut?

Total cost drives no action. Cost **concentration** does.

- Share of spend from the top 5 users, the top 3 agents, and the top model.
- Cost per active user per month. This is the one number finance accepts.
- Spend sent to an expensive model for work a cheap model handles.
- Money already saved by prompt caching. We store `cache_read_tokens` today.

### Decision: who pays for it?

Cost split by team or user group. Most orgs must charge the cost back, or at
least explain the invoice internally. An admin who cannot attribute cost to a
cost center cannot grow the deployment. This blocks expansion.

`User__UserGroup` already gives us the join.

### Decision: did the rollout work?

Message volume is a trap. It rises when three people go heavy.

Measure breadth first, then habit, then depth:

- Distinct humans who used Onyx in the period.
- How many use it every week, and whether that count rises.
- Multi-turn sessions versus one-question-and-leave.
- The funnel: invited, first message, five messages, weekly habit.

The drop-off point in the funnel tells the admin what to fix. A drop before the
first message means onboarding. A drop after it means answer quality.

### Decision: is the quality good?

The admin cannot read conversations. Give them proxies, and give them trends.
Nobody knows what a good absolute thumbs-down rate is.

- Negative feedback rate.
- Regeneration rate.
- Sessions abandoned after one answer.
- Answers where retrieval returned nothing.

### Decision: what do I do next to improve it?

This section is the most actionable, and it does not exist today.

- Connectors that are indexed but never cited.
- Topics that people ask often and Onyx answers badly.
- Agents that nobody uses.

Each item maps to one concrete action: add a source, write a document, delete
an agent.

### Decision: am I exposed?

Admins do not want a security console here. They want a short "look at this"
list, with names on it.

- A user whose usage jumped 10x.
- Access to sensitive sources.
- Traffic from a service account or API key, not a human.
- Activity from an employee who left and kept an account.

## The flagship: the knowledge gap report

Every vendor can report spend and logins. Only Onyx knows **what the
organization tries to learn and fails to find.**

A monthly artifact that lists the top unanswered questions, clustered by topic,
with the missing sources named, is worth more than the full cost breakdown. It
tells the admin something about their own company that they cannot get anywhere
else. It also makes the strongest renewal argument that exists.

Treat this as the headline of the report, not an extra tab.

## Three artifacts, not one zip

The current report tries to be one thing. The admin needs three, at three
cadences. This is the main structural change.

| Artifact                | Cadence   | Form                              | Purpose                          |
| ----------------------- | --------- | --------------------------------- | -------------------------------- |
| **Pulse**               | Monthly   | Pushed to email or Slack, no download | Tell the admin if anything changed |
| **Review pack**         | Quarterly | A PDF the admin forwards to their boss | Defend the spend and the rollout |
| **Investigation export**| On demand | The raw CSVs we build today       | Answer a specific question, feed BI |

The pulse must be pushed. An artifact that needs a download and a spreadsheet
gets read once.

## The one screen

If the pulse were a single screen, it holds eight items:

1. Active users, and the change.
2. Spend, and the change.
3. Cost per active user.
4. Percent of seats dormant, with the list.
5. Top 3 cost concentrations.
6. Quality trend, one line.
7. Top 5 unanswered topics.
8. One anomaly callout.

Everything else lives one click deeper.

## The PDF review pack

The review pack must be a PDF. An admin forwards it to a VP or a CFO. Those
people do not open a zip of CSVs, and they do not log in to an admin panel. The
PDF is the artifact that travels.

### Build it in pure Python with ReportLab

Use **ReportLab** (BSD licensed). Write the document in Python. Do not template
markdown, do not render HTML, and do not drive a browser.

ReportLab supplies everything the pack needs:

- `platypus` flows content into pages. It splits long tables across pages and
  repeats the header row.
- `graphics.charts` draws bar, line, and pie charts as native PDF vectors.
- The PDF base-14 fonts (Helvetica, Times) need no embedding. A brand font
  works too, but vendor the TTF in the repo. Never fetch a font at render time.

Measured on a representative pack (40-row table across 2 pages, one line chart,
one bar chart): **13 ms, 4.4 KB**. No subprocess, no browser.

### The shared layer is the data model, not the text

Build one typed aggregate object, and give each output its own renderer:

| Output       | Renderer                          |
| ------------ | --------------------------------- |
| PDF          | ReportLab document builder        |
| Email digest | HTML with inlined styles          |
| Slack digest | Slack blocks                      |
| CSV rollups  | The existing writers              |

All four read the same aggregate object, so the numbers always agree. Sharing a
data model is stronger than sharing a markdown string. Markdown cannot express a
chart, a page break, or a repeated table header, so it would have leaked layout
concerns into the shared layer anyway.

### Pipeline

1. Query the aggregates into the typed object. Same queries as the CSV rollups.
2. Build the ReportLab document from that object.
3. Save the PDF to the file store next to the zip, under the same `report_id`.

This runs in the existing Celery report task.

### Alternatives considered

- **Chromium through Playwright.** It works, and it needs no new dependency,
  because the image already installs Chromium (`backend/Dockerfile:124`) and
  already launches it for the web connector. It also renders correctly with no
  network (verified below). It still loses: a browser launch costs about 470 ms
  and a few hundred MB of RSS, versus 13 ms for ReportLab, and it drags a
  browser process, a template layer, and hand-written SVG into the report path.
- **WeasyPrint.** Adds a Python dependency plus pango system libraries, and
  still makes us write CSS to control pagination.
- **Markdown plus Jinja2.** A lossy intermediate format. It cannot express
  charts or pagination, so every hard part would still need solving elsewhere.

### Air-gap status

Verified inside the shipped image with `docker run --network none`:

- Chromium launches and prints a PDF with tables, inline SVG, and real fonts.
  Text extracts correctly. So the browser path is air-gap safe if we ever want
  it.
- ReportLab needs no network by construction, and the base-14 fonts live inside
  the PDF spec.

Note that the air-gap CI job only starts `api_server`, `inference_model_server`,
and `minio`. It does not exercise the background worker or a browser. Any
air-gap claim for a new render path needs its own check.

### Constraints to respect

- Determinism. The same period must produce the same PDF. Do not stamp a
  render timestamp inside the content body.
- Size. Cap the page count. The pack is a summary, not the export.
- Anonymized mode. The PDF must honor it, the same as the CSVs.
- Failure isolation. A PDF failure must not fail the zip. Generate them
  independently.

## Anti-metrics

Do not put these in a report. They look informative and drive no decision:

- Total messages, total tokens, total sessions.
- Average response time.
- Any cumulative all-time count.

## What the raw export still needs

The investigation export stays. Fix its defects:

- Add `summary.csv`, `manifest.json` (schema version, period, timezone, row
  counts, generator version), and a `README.md` that defines every column.
- Add pre-built rollups: by team, by agent, by model, by day.
- Fix `users.csv`: email, role, groups, created date, last active, seat state.
- State the units. Name the currency. Snapshot the price table, so the numbers
  stay reproducible after prices change.
- Warn when the period is incomplete. If the usage rollup started after the
  period start, say so on the report. Otherwise a partial month reads as a
  full one.
- Support an anonymized mode. Some EU customers cannot legally receive per
  person usage. Hash the email with a per-report salt.

## Build order

Ordered by value per unit of work. The first two are independent of each other.

1. **Seat ledger.** Fix `users.csv` and derive the dormant-seat list. Small
   change, and it makes every other file joinable.
2. **Knowledge gap report.** The differentiated artifact.
3. **Team and agent dimensions** on the cost breakdown. Unblocks chargeback.
4. **Summary, manifest, and README** on the export.
5. **Extend the PDF review pack.** The shipped pack summarizes spend and
   adoption by person, model, and flow. Add the missing dimensions from steps
   1 to 3 as they become available.
6. **Scheduled pulse** to email or Slack. The Celery beat already exists, and
   the existing typed aggregate object supplies the content.
