---
name: merge-dependabot-prs
description: >
  Triages and lands a batch of open Dependabot PRs in the Onyx repo, where main
  is gated exclusively by GitHub's merge queue: approves and enqueues green PRs,
  closes superseded duplicates, fixes mechanical CI failures (stale
  backend/requirements exports, stale bun.lock), tells real regressions apart
  from pre-existing breakage and flakes, and tracks every PR through to merge.
  Use when the user asks to merge, clean up, clear out, or land Dependabot (or
  similar bot-authored) PRs.
license: MIT
compatibility: Requires git, pre-commit, uv, bun, ods (the repo venv's devtools script), and gh (GitHub CLI) authenticated with write access to onyx-dot-app/onyx.
metadata:
  author: jmelahman
  version: "1.1"
allowed-tools: Bash(gh:*), Bash(git:*), Bash(pre-commit:*), Bash(bun install:*), Bash(ods audit:*)
---

# Merge Dependabot PRs

Treat each blocked PR as its own small diagnosis, not one "just merge it" action.

**Confirm before anything consequential.** Approving, closing, pushing to a PR
branch, merging main into someone's branch, and rerunning CI all touch shared
state. Triage everything into buckets first, then confirm the plan per bucket
with `AskUserQuestion` — not per PR, and not after the fact. Re-confirm if a
genuinely new kind of problem appears mid-flight (e.g. a real regression where
a mechanical fix was expected).

## How Onyx gates merges

- `main` merges **exclusively through the merge queue** ("Main Protection"
  ruleset). Enqueue with `gh pr merge <pr> --auto` — no strategy flag; the
  queue picks the method. `--squash`/`--merge`/`--rebase` will be rejected.
- Required checks: `quality-checks`, `playwright-required`, `database-tests`,
  `backend-check`, `mypy-check`, `Jest Tests`, `required`.
- `required` (in `pr-integration-tests.yml`) and `playwright-required` (in
  `pr-playwright-tests.yml`) are aggregate `needs: [...]` + `if: always()`
  jobs over the slow integration/playwright matrices. If either is *absent*
  from `gh pr checks`, its matrix is still running — the PR isn't blocked.
  (`merge-group.yml` provides instant-pass stubs of the same names inside the
  queue itself.)
- `mergeStateStatus`/`autoMergeRequest` are unreliable for "is it actually
  queued" — query the queue directly: [references/graphql-queries.md](references/graphql-queries.md).

## 1. Discover the batch

```bash
gh pr list --search "is:open author:app/dependabot assignee:<user>" \
  --json number,title,headRefName,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
```

PRs are labeled by ecosystem (`dependabot:python`, `dependabot:javascript`,
`dependabot:docker`, `dependabot:actions`, plus `dependabot:sandbox`) and
assigned per `.github/dependabot.yml`. Flag duplicates: two PRs bumping the
same package, or a manual bump PR overlapping a bot one.

## 2. Triage into buckets, confirm the plan

These PRs aren't in a rush. Wait for every check to complete — required and
advisory alike — and treat any red check as a failure to classify, never as
noise to skip. Two advisory checks matter here even though the queue ignores
them:

- `storybook-build` (`pr-storybook-build.yml`) on `web/**` changes — never
  gates the queue, but pages Slack if broken post-merge.
- `audit` (`audit.yml`) — runs on every lockfile, `pyproject.toml`,
  `.github/workflows/**`, and `tools/ods/**` change, so it runs on almost every
  Dependabot PR. Treat it as **required for this skill**: a Dependabot PR does
  not get enqueued while `audit` is red. A red `audit` means the bump either
  pulled in a vulnerable version or landed next to one, and merging it ships
  the finding.

- **Green & ready** — every check completed and passing, advisory included.
- **Failing — mechanical** — only a generated/lock file wasn't regenerated
  after the bump (see step 5 for the Onyx cases).
- **Failing — needs diagnosis** — anything else; requires reading the failing
  job's log first, never just the check name.
- **Conflicting** — real merge conflict against main.
- **Superseded** — a newer PR in the batch covers it.

Independent of bucket, assess compatibility: note each PR's semver jump and
whether the package is production or dev-only. Major bumps (and 0.x minors,
which semver allows to break) are never covered by a blanket "enqueue the
green ones" — green CI proves the build, not the behavior. Surface each one
individually in the confirmation with a one-line breaking-changes summary
from the release notes Dependabot embeds in the PR body, and let the user opt
in per PR.

Summarize buckets and proposed actions, confirm with `AskUserQuestion`, then act.

## 3. Green: audit, approve, enqueue

Run `ods audit` on the PR's code before you enqueue it. CI's `audit` job covers
this, but it is skipped when the PR touches no audited path, and it is advisory
in the queue — so confirm it yourself for every Dependabot PR.

```bash
gh pr checkout <pr>
source .venv/bin/activate   # ods ships in the repo venv
ods audit --fail-on=critical
```

`ods audit` scans `bun.lock` and `uv.lock` plus open Dependabot alerts, and
exits non-zero on an unignored finding at or above `--fail-on`
([tools/ods/README.md](../../../tools/ods/README.md)). It reads the **working
tree**, so the PR branch must be checked out — a run on `main` says nothing
about the bump.

**If it exits non-zero, STOP.** Don't enqueue and don't try to work out whether
the finding came from this bump or was already on `main`. Report the advisory ids
and let the user say how to proceed.

Then, once clean:

```bash
gh pr review <pr> --approve
gh pr merge <pr> --auto
```

If a PR falls out of the queue (e.g. `head_ref_force_pushed` after a Dependabot
rebase), re-running `gh pr merge <pr> --auto` is routine, not a failure.

## 4. Superseded: comment which PR supersedes it, then `gh pr close`

## 5. Mechanical: fix in an isolated worktree

Once the bucket is approved, individual stale-generated-file fixes don't need
per-PR confirmation. Known Onyx cases:

- **uv bumps** (`dependabot:python`): the exported `backend/requirements/*.txt`
  files go stale when only `pyproject.toml`/`uv.lock` were bumped. Regenerate
  via the same pre-commit hooks CI uses:
  ```bash
  pre-commit run --files pyproject.toml uv.lock backend/requirements/*.txt
  ```
- **bun bumps** (`dependabot:javascript`): stale `bun.lock` — run
  `bun install` in the bumped directory (repo root or `web/`).

Getting the branch: prefer the harness's isolated-worktree feature if it has
one (Claude Code: `EnterWorktree`). Otherwise, if the current checkout is
clean, work in place — `gh pr checkout <pr>`, fix, push, and return to the
previous branch. If neither applies (e.g. dirty checkout), ask the user where
to resolve (`AskUserQuestion`) rather than picking a spot — and steer away
from tmpfs paths like `/tmp`, which can hit "Disk quota exceeded"
mid-post-checkout hook (`uv sync`/`bun install`) even when they look roomy.

## 6. Needs diagnosis: read the failing job's log, then classify

- **Pre-existing** — the same job also fails on main's current HEAD
  ([references/graphql-queries.md](references/graphql-queries.md)). Not this
  PR's problem; leave it and say so.
- **External flake** (rate limit, transient network, shared infra) — confirm
  from the log, rerun once (`gh run rerun <runId> --failed`). If the same
  failure recurs, stop and ask — a persisting "flake" may not be one.
- **Real regression from the bump** — diagnose the root cause, then ask whether
  to fix or leave it. Never patch unrelated source just to force CI green.

## 7. Conflicts

- **Untouched Dependabot branch**: comment `@dependabot rebase` (or
  `recreate`) — Dependabot owns the branch and will redo it properly.
- **Branch we already pushed fixes to**: `@dependabot rebase` discards
  non-Dependabot commits. Instead rebase onto `origin/main` yourself, rerun
  the step 5 regeneration if lockfiles conflicted, push with
  `--force-with-lease`, and verify `git diff origin/main...HEAD --stat` still
  shows only the intended bump. If a pre-push hook trips on a stale local
  cache (e.g. dev type-gen referencing a file deleted upstream), clear the
  cache and retry — don't skip the hook.

## 8. Track to completion

Prefer one polling loop (e.g. `Monitor`) over repeated manual checks: watch
both queue state and PR state (`MERGED`/`CLOSED`), and surface new failures as
they appear rather than staying silent until success.

## 9. Report

```
Merged (N): #A, #B, #C
Closed as superseded (N): #D (superseded by #E)
Left for you (N): #F — <specific unresolved reason>
```
