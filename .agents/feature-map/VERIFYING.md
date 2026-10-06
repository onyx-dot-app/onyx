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

If a path is not in the table, the area is unmapped. Do not treat that as low
risk. Read the nearest code and its tests yourself, and say in your report that
you verified against an unmapped area.

## Step 3: Read the components

For each component, read its document in [components/](components/).

- **§1 and §4** tell you what the code is supposed to do. Compare that to what the
  diff now makes it do. A mismatch is either a bug or a doc that needs updating in
  this same PR.
- **§3** tells you which tables are involved. If the diff adds a column, check
  whether a migration exists and whether the component doc still describes the
  schema correctly.

Follow the "Depends on" links in **§6** for any component the change reaches into.

## Step 4: Check the invariants

Walk **§5 Contracts and invariants** for every component, line by line.

This is the highest-value step and the one an agent is most tempted to skip. These
are the rules a change breaks *silently*. Nothing fails; the product is just wrong
later, under load, or for one tenant.

For each invariant, state explicitly whether the change preserves it, breaks it, or
does not touch it. Do not summarize. An unchecked invariant is an unverified change.

## Step 5: Walk the blast radius

Find the row in **§7 Blast radius** matching the *kind* of change in the diff. Check
each item it names. Most real defects in a review live here, in the file the author
did not think to open.

Pay particular attention to hand-mirrored contracts, because nothing enforces them:

- The streaming packet enum exists in Python, in web TypeScript, and in mobile
  TypeScript.
- A new built-in tool needs a class, a `BUILT_IN_TOOL_MAP` entry, a seeded database
  row, and a frontend renderer. Custom tools follow other registration paths.
- Prompt text and reminder placement change model behaviour without changing any
  type.

## Step 6: Gather evidence

Run **§8 How to verify a change** for each component.

1. **Tests.** Run the ones the component names. If the change adds behaviour and
   adds no test, say so plainly. Integration tests are preferred in this repo. Check
   `backend/AGENTS.md` for the commands and the required environment.
2. **Manual reproduction.** Follow the steps in §8. For browser flows, drive the
   browser with `claude-in-chrome` against the user's real Chrome. For other surfaces,
   use the client the component's §8 names. Read
   `backend/log/<service>_debug.log` for backend behaviour.
3. **Negative check.** Verify the failure mode too, not only the happy path. Stop
   mid-stream, revoke a permission, send an empty input, reload the page.

State what you ran and what you saw. "Tests pass" with no output is not evidence.

## Step 7: Read the footguns

**§9 Footguns** lists the traps in each component. Check whether the change walked
into one. This is short and it catches a specific class of confident mistake.

## Step 8: Check the repo-wide rules

Independent of the map, every change is subject to:

- `AGENTS.md` at the repo root: typing, Simplified Technical English in prose.
- `backend/AGENTS.md`: Celery, migrations, error handling, LLM tracing. Every LLM
  call needs a generation span tagged with `LLMFlow`. Shared-client calls that set no
  flow emit `UNTAGGED_*` sentinels (`backend/onyx/llm/multi_llm.py:MultiLLM.invoke`,
  `MultiLLM.stream`). Direct-provider calls without a span emit nothing.
- `web/AGENTS.md`: the component rules. Opal over refresh-components, no raw HTML
  form elements, no raw text nodes, no `lucide-react`, no `dark:` modifier, design
  tokens only.
- `mobile/AGENTS.md`: mobile does **not** follow the web rules.
- `CONTRIBUTING.md`, "Engineering Best Practices".
- `pre-commit run --files <changed paths>`.

## Step 9: Report

Structure the report so a human can act on it:

- **What the change does**, in your own words, from reading the diff.
- **Components touched**, and whether each behaves as its document describes.
- **Invariants checked**, with the verdict on each. Name the ones you could not check.
- **Blast radius items checked**, and anything the change missed.
- **Evidence**: commands run, output, manual steps, what you observed.
- **Findings**, ranked by severity, each with a concrete failure scenario.
- **Gaps**: what you could not verify, and why. Be explicit. An honest gap is worth
  more than a confident guess.

---

## Keeping the map honest

If the change alters behaviour a component document describes, the document must
change in the same pull request. A stale map is worse than no map, because the next
agent will trust it.

If you verified against an area with no component document, add one, or at minimum
add the path to [PATHS.md](PATHS.md) and the component to [INDEX.md](INDEX.md) as a
planned entry.
