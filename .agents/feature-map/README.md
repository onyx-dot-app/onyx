# Onyx Feature Map

A map of what Onyx **is**: every product surface, what it does, the code that
implements it, and how the pieces connect.

It exists for one job: let an agent that starts with **no context** verify that a
change is correct and complete. Not "does it compile", but "does it do the right
thing, and what else did it just break".

## How to use this map

### To verify a pull request

The full procedure is [VERIFYING.md](VERIFYING.md). In short:

1. Get the changed paths: `git diff --name-only <base>...HEAD`
2. Look each path up in [PATHS.md](PATHS.md). That gives you the components you touched.
3. Read each component doc. Sections 1 and 4 tell you what the code is *supposed* to do.
4. Check the diff against **§5 Contracts and invariants**. These are the rules a
   change can break silently.
5. Walk **§7 Blast radius**. It lists what else to check for your kind of change.
6. Run **§8 How to verify**. Tests plus a manual reproduction.
7. Repeat for every component listed under "Depends on" that your change reaches into.

### To understand a feature before building on it

Start at [INDEX.md](INDEX.md), find the domain, read the component doc.
Follow `[[links]]` to neighbours.

### Vocabulary

Onyx overloads several words (persona/agent, chunk/section, cc-pair). Read
[GLOSSARY.md](GLOSSARY.md) before you trust your intuition about a name.

## Files

| File | What it holds |
|---|---|
| [VERIFYING.md](VERIFYING.md) | The step-by-step procedure for checking a PR with this map. |
| [INDEX.md](INDEX.md) | The sitemap. Every component, grouped by domain. |
| [PATHS.md](PATHS.md) | Reverse lookup: code path → component. Start here for a diff. |
| [GLOSSARY.md](GLOSSARY.md) | Domain vocabulary and the words Onyx overloads. |
| [components/](components/) | One document per component. |

## The component document schema

Every file in `components/` has the same header (§0) and nine numbered sections
(`## 1.` to `## 9.`), in the same order, so an agent can jump straight to the section
it needs.

| § | Section | Answers |
|---|---|---|
| 0 | Header | Domain, edition (CE/EE), owned code paths |
| 1 | What the user experiences | Product behaviour, no code |
| 2 | Surfaces | Routes, endpoints, tasks, env vars |
| 3 | Data model | Tables and columns |
| 4 | How it works | The flow, each step naming `file:function` |
| 5 | Contracts and invariants | Rules a change can break silently |
| 6 | Relationships | Depends on / depended on by |
| 7 | Blast radius | Change type → what else to check |
| 8 | How to verify a change | Tests, commands, manual reproduction |
| 9 | Footguns | Traps and non-obvious behaviour |

## Rules for writing and updating

- **Every technical claim carries a `path:symbol` reference.** A claim with no
  reference is a guess, and a guess in this map is worse than a gap.
- **Write what is true now**, not what is planned. No changelogs, no history.
- **Do not duplicate the code.** Describe intent, contracts, and connections.
  Line-by-line restatement goes stale in a week.
- **Prefer symbol references over line numbers.** `chat/llm_loop.py:run_llm_loop`
  survives edits; `llm_loop.py:412` does not.
- **If you change a component, update its doc in the same PR.** A stale map is a
  liability.
- **Every component records the commit it was last checked against**, on its
  `**Verified against:** \`<sha>\` (<date>)` line. When you re-check a whole
  document against the code, set the line to the commit you checked and today's
  date. A small doc fix in a code PR does not change it. To find the components
  that may be stale, list the commits since that hash on the component's code
  paths: `git log <sha>..HEAD -- <paths from PATHS.md>`.
- Prose follows the ASD-STE100 rules in the root `AGENTS.md`: short sentences,
  active voice, one word for one idea.

## The integrity check

`check_feature_map.py` runs as the `feature-map-integrity` pre-commit hook on every
commit, locally and in CI. It fails when:

- a component does not have sections `## 1.` to `## 9.` in order, or has no
  `**Verified against:**` line;
- a component is missing from `INDEX.md`, or `PATHS.md` names a component that does
  not exist;
- a `[[component]]` link does not resolve;
- a backticked repo path does not exist. A short path such as `db/models.py`
  resolves against the usual roots (`backend/onyx/`, `web/src/`, and others).

So a PR that renames or deletes a file the map cites must update the map too. If a
code span looks like a path but is not meant to exist in the repo (a build output,
a runtime path, or a statement that a file does not exist), add it to
`path-allowlist.txt`. Run the check by hand with
`python3 .agents/feature-map/check_feature_map.py`.

## The stale-document reminder

`stale_docs.py` takes a list of changed files, maps each one to its components
through `PATHS.md` (longest prefix wins, tests and `.agents/` ignored), and names
every component whose code changed but whose document did not. Run it by hand with
`python3 .agents/feature-map/stale_docs.py <files>`. The agent Stop hook from #15555
runs it on the branch's changes when an agent ends a turn, so the agent decides
whether the document needs an update while it still knows what it changed. With the
hook, it names each component at most once per session.

The check catches broken references only. It cannot tell when a description is
wrong while every path it cites still exists. That is why each component records
the commit it was last verified against.

## Daily reconciliation

The `Feature Map Reconcile` workflow (`.github/workflows/feature-map-reconcile.yml`)
runs `reconcile.py` once a day. It catches what the per-PR rules miss: a code PR
that changed behaviour without a document update.

1. It reviews the commits merged to `main` since the commit in `RECONCILED`. On the
   first run, it reviews the past 7 days.
2. It maps each commit to its components with `stale_docs.py`. A commit that
   already updated a component's document is skipped for that component.
3. It runs one Claude Code agent per affected component, in parallel. Each agent
   reads the diffs, checks them against the code, and edits only its own document.
   The prompt is `.github/prompts/feature-map-reconcile-component.md`.
4. An integrator agent applies the changes that other files need, such as new
   `PATHS.md` rows for code that no component owns. The prompt is
   `.github/prompts/feature-map-reconcile-integrate.md`.
5. The integrity check runs. The integrator fixes any error it reports.
6. The workflow opens a pull request on `auto/feature-map-reconcile` for review.

A reconciliation does not change `Verified against` lines, because it checks only
the new commits, not whole documents. The workflow skips a day while the previous
reconciliation pull request is still open. `RECONCILED` moves forward only when
every component agent succeeds, so a failed component is retried on the next run.
Run it by hand with `python3 .agents/feature-map/reconcile.py` (prints the plan) or
from the Actions tab with an optional `since` commit.
