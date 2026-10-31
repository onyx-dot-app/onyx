# Verifying a Change With the Feature Map

The procedure a skill or an agent follows to check a pull request against the
product, not just against the compiler. Written for an agent that starts with no
context on this codebase.

The goal is to answer three questions:

1. **Does the change do what it claims?**
2. **Does it break a contract somewhere else?**
3. **Is there evidence it works, that someone else can re-run?**

---

## Step 1: Establish what changed

```bash
git diff --name-only <base>...HEAD     # the files
git diff <base>...HEAD                 # the actual change
git log <base>...HEAD --oneline        # the claimed intent
gh pr view --json title,body           # the stated intent
```

Read the whole diff before reading any documentation. Form your own view of what
the change does. Then check that view against the map, so the map corrects you
rather than anchoring you.

## Step 2: Map the paths to components

Look every changed path up in [PATHS.md](PATHS.md). Longest prefix wins. Collect
the set of components.

A path under `## Not mapped` has no component; its row gives the reason. If no
row covers a path, the area is unmapped. Do not treat
that as low risk. Read the nearest code and its tests yourself, and say in your
report that you verified against an unmapped area.

## Step 3: Read the components

For each component, read its document in [components/](components/).

- **User experience** (or **Callers**, for a component that other code builds
  on) tells you what the component must do for the people and code that use it.
  **Scope** and **Architecture** tell you how the code does it and what it owns.
  Compare that to what the diff makes it do. A mismatch is either a bug or a
  document that needs an edit in this same PR.
- **Decisions** tell you which designs were chosen on purpose. A change that
  reverses one needs a reason.

Follow the links in **Dependencies** for any component the change reaches into.

## Step 4: Check the contracts

Check two sets of contracts:

- every contract or recipe that cites a file the diff touches, from any document:

  ```bash
  python3 .agents/feature-map/stale_docs.py --cited $(git diff --name-only <base>...HEAD)
  ```

- each contract of the components from Step 2 whose rule the diff plausibly
  affects, even when the contract does not cite a changed file.

This is the highest-value step and the one an agent is most tempted to skip. These
are the rules a change breaks *silently*. Nothing fails; the product is just wrong
later, under load, or for one tenant.

Read **Contracts and traps** of each component from Step 2 to find the second set.
For each contract in the two sets, name it by key (`[[slug#key]]`) and state
whether the change preserves it or breaks it. Do not summarize. You do not need a
verdict on a contract that neither cites the diff nor governs what it changes.

## Step 5: Check what else the change must touch

Each contract names what else to check when its code changes. **Recipes** list
every place a common addition must reach, and the Common tasks table in
[INDEX.md](INDEX.md) gives the order across components. Check each item. Most
real defects in a review live here, in the file the author did not think to open.

Pay particular attention to contracts that the code mirrors by hand, because
nothing enforces them. The owning components name them, for example
[[streaming-protocol]] for packet types and [[tools-framework]] for built-in
tools.

## Step 6: Gather evidence

1. **Tests.** Run the tests the component's **Verification** names, and the
   tests next to the changed code. If the change adds behaviour and adds no test,
   say so plainly. Integration tests are preferred in this repo.

   ```bash
   uv run pytest -xv backend/tests/unit/<path>
   uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/<path>
   uv run --env-file .vscode/.env pytest backend/tests/integration/<path>
   cd web && bun run playwright <spec>
   ```

   `backend/AGENTS.md` has the required environment and secrets.
2. **Manual reproduction.** Use the checks in the component's **Verification**.
   The local app is at `http://localhost:3000`. Sign in as
   `admin_user@example.com` with `TestPassword123!`. Call the backend through the
   frontend (`http://localhost:3000/api/...`). Read
   `backend/log/<service>_debug.log` for backend behaviour.
3. **Negative check.** Verify the failure mode too, not only the happy path. Stop
   mid-stream, revoke a permission, send an empty input, reload the page.

State what you ran and what you saw. "Tests pass" with no output is not evidence.

## Step 7: Check the repo-wide rules

Independent of the map, check the change against the rules in these files:

- `AGENTS.md` at the repo root, and the `AGENTS.md` of each area the diff touches:
  `backend/AGENTS.md`, `web/AGENTS.md`, `mobile/AGENTS.md`. Mobile does not follow
  the web rules.
- [CROSS-CUTTING.md](CROSS-CUTTING.md), for the rules every component follows.
- `CONTRIBUTING.md`, "Engineering Best Practices".
- `pre-commit run --files <changed paths>`.

## Step 8: Report

Structure the report so a human can act on it:

- **What the change does**, in your own words, from reading the diff.
- **Components touched**, and whether each behaves as its document describes.
- **Contracts checked**, by key, with the verdict on each. Name the ones you
  could not check.
- **Related changes checked**, and anything the change missed.
- **Evidence**: commands run, output, manual steps, what you observed.
- **Findings**, ranked by severity, each with a concrete failure scenario.
- **Gaps**: what you could not verify, and why. Be explicit. An honest gap is worth
  more than a confident guess.

---

## Keeping the map true

If the change makes a document wrong, the document changes in the same pull
request. "Editing judgment" in [README.md](README.md) says what to edit: only the
parts the change touches, and only what a future agent needs. A diff that
rewrites untouched parts of a document belongs in a verify pass, not in a code
PR.
