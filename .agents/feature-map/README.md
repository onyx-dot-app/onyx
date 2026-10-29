# Onyx Feature Map

A map of how Onyx works, for a coding agent that starts a task with no context.
It records what the code cannot tell you quickly:

- where each responsibility lives, and what each component does not own;
- how the parts connect across files and services;
- the rules a change can break without a failing test;
- why the design is the way it is;
- known issues and limitations;
- how to do common tasks correctly.

It does not restate the code. An agent can list endpoints, columns, env vars and
call sites in seconds with `git grep`. The map spends its words on what a search
cannot show.

This file is the only full statement of the map's rules. Other files link here.

## How to use this map

- **For a change to existing code:** look up each path you will touch in
  [PATHS.md](PATHS.md) and read the component documents it names. Read
  **Contracts and traps** first. Follow the links in **Dependencies** for each
  neighbour your change reaches.
- **To review a diff or PR:** follow [VERIFYING.md](VERIFYING.md).
- **Before you trust a name:** read [GLOSSARY.md](GLOSSARY.md). Onyx uses words
  such as Persona, Tool, turn and SearchDoc in more than one sense.

## Files

| File | What it holds |
|---|---|
| [INDEX.md](INDEX.md) | Every component with its summary, grouped by domain. |
| [PATHS.md](PATHS.md) | Code path to component. The only record of ownership. |
| [VERIFYING.md](VERIFYING.md) | How to review a PR with this map, and the shared test commands. |
| [GLOSSARY.md](GLOSSARY.md) | Domain words and the words Onyx overloads. |
| [components/](components/) | One document per component. A family of small components can share a subdirectory, such as the per-connector documents. Component names are unique across all directories. |

## Components

A component is a product responsibility, not a code layer. A frontend gets its
own component only when it holds rules of its own, such as state ownership or
settlement. Split a component when it holds two areas that change separately.

A component that people use directly starts with **User experience**: end users,
admins, operators and API callers. A component that other code builds on starts
with **Callers** instead. A component has one of the two, never both.

Map each path in [PATHS.md](PATHS.md) to one component. List two only when both
own rules in that code, and more than two only for a reason you can state. When
two components share a file, a fact about it goes in the component whose User
experience or Callers the behaviour serves. A component can own a rule whose code
another component owns in PATHS.md. Cite that code in the rule; the editing brief
reaches the document through the citation. Do not add a second owner row for it.
These are guidance; the check does not count owners.

Code that no component owns goes in the `## Not mapped` table of PATHS.md, with
the reason. Every PATHS.md table has two columns: the backticked paths, then the
component slugs or the reason.

## The component document

**Header.** A `# Title`, a summary of one or two sentences in a `>` block, then
these lines in this order:

```
**Verified against:** `<sha>` (YYYY-MM-DD)
**Edition:** CE. EE adds ...
```

The INDEX.md row for the component repeats the summary word for word;
`check_feature_map.py --fix` copies it. The INDEX.md section that lists the
component is its domain.

**Sections,** in this order. Leave out an optional section that has nothing to
say. Do not write "none" or "not applicable".

| Section | Required | What it holds |
|---|---|---|
| `## User experience` | one of these two | What people can do, and what they see when it works and when it fails. Not the screen layout. This is the intent that a change is judged against. |
| `## Callers` | one of these two | The interface, who calls it (the developers who build on it and the components that call it, with links), and the contract keys a caller must keep. Not a success and failure story for each caller. |
| `## Scope` | yes | The responsibilities the component holds, and what each neighbour owns instead. No file paths: PATHS.md is the only ownership record. |
| `## Architecture` | yes | The entry points that matter and the flows that cross files, each with its reason. A diagram helps. |
| `## Contracts and traps` | yes | Keyed rules a change can break without a failing test, and traps an agent will step in. |
| `## Decisions` | optional | Why the design is this way, and the alternatives that were rejected. |
| `## Known issues` | optional | Real gaps and limitations, kept apart from traps. |
| `## Dependencies` | yes | What this component depends on. One `- [[slug]]: reason` line each. |
| `## Recipes` | optional | Keyed recipes: how to add common things, investigate a report, or set up state for a test or a reproduction. |
| `## Verification` | optional | Test directories and harnesses for the component, and checks that only a person can do. |

[citations.md](components/citations.md) and
[rate-and-usage-limits.md](components/rate-and-usage-limits.md) are examples.

**Contracts and traps.** Each item starts with its number and a key, then the
rule in bold. The rule names the code it is about and what else to check:

```
1. `unresolved-citation-silent` **An unresolved citation renders as nothing.** ...
```

- A key is lower-case kebab case and unique in its document.
- Keep the key when you edit the rule. Never reuse the key of a deleted rule.
- Cite a contract by key: `[[citations#unresolved-citation-silent]]`, or
  `[[#unresolved-citation-silent]]` in the same document. Never cite one by its
  number, because numbers change when the list changes.
- A new contract states a new rule, not one more case of a rule the section has.
  When the section feels long, merge rules that say the same thing, or delete a
  rule that a test or the code enforces. There is no count limit.

**Dependencies.** List only what this component depends on. To find what depends
on a component, run `git grep '\[\[<slug>'` in the map.

**Recipes.** Each recipe is a `-` item with a key, like a contract:

```
- `new-connector` **A new connector.** Copy the `youtrack` source. ...
```

Keys follow the contract key rules and share one namespace with them. Cite a
recipe as `[[connectors#new-connector]]`. A recipe that adds something names a
reference instance to copy and how to find the current set, for example "copy
the `youtrack` connector; list the sources with `git ls-files`". Investigation
and setup recipes need no reference instance. Indent the steps of a recipe under
its item.

The Common tasks table in INDEX.md is the only record of the order of recipes.
Add a row when a task needs recipes from more than one document. Each cell links
recipe keys or contract keys by `[[slug#key]]`; the two share one namespace. A
recipe does not link the next one.

## Rules for writing

**A fact belongs in the map when the code cannot tell it quickly.** It spans
files, explains a reason, or warns of a trap. If an agent can learn it in a
minute by opening one file, leave it to the code.

**Do not write:**
- Tables of endpoints, env vars, columns or call sites. Name the entry point and
  let the agent search. Keep one row only when the value is surprising, for
  example "`token_budget` is stored in thousands".
- Exact counts and closed lists ("the twelve connectors that…"). They go stale
  with the next addition. Say how to find the current set.
- UI layout, copy or styling, such as focus order, icons, colours or widths.
- Step-by-step walkthroughs of one function.
- History: PR numbers, migration history, and words such as "legacy", "now",
  "no longer" and "currently". State what is true at the verified commit, and
  leave history to git. The check fails only on PR numbers.
- Shared boilerplate: the standard test commands and the local login live in
  [VERIFYING.md](VERIFYING.md).

**Keep:**
- Rules about compatibility across versions: old clients, rolling deploys,
  running pods or sandboxes that keep an old image, and buffered data across a
  deploy. They go in **Contracts and traps**.
- A table that encodes a rule across resources, such as a permission or policy
  matrix. A list of code is not such a table.
- False leads: a name, file or function that looks like the right place but is
  not.
- Diagnostic and state-setup steps that only this component needs. They go in
  **Recipes**.

**State each fact once.** Write a fact in the component that owns it and link to
it from the others. When an in-tree README or a customer doc covers a topic, link
to it; do not repeat it. ARCHITECTURE.md, CROSS-CUTTING.md and GLOSSARY.md link
to the owning contract and add at most one sentence.

**Keep documents short.** Cut what does not earn its place; do not trim to a line
count. **Verification** names test directories and harnesses, not each test file.
A document that grows past about 300 lines deserves a look at what to merge or
split. The editing brief gives each document's size and its growth on the branch
for this reason. The check does not count lines.

**Write in ASD-STE100 style.** Short sentences, active voice, one word for one
idea (root `AGENTS.md`).

## References to code

- A path is a repo-root path, or a path under one of these roots: `backend/onyx/`,
  `backend/ee/onyx/`, `backend/`, `web/src/`, `web/`, `mobile/src/`,
  `widget/src/`, `desktop/src/`. A path such as `server/query_and_chat/token_limit.py`
  resolves under `backend/onyx/`. There is no other search: a bare file name
  resolves only when the file sits directly under the repo root or one of these
  roots.
- When a contract, trap or architecture claim names code, prefer `path:symbol`
  or `path:Class.method` to a bare path: the editing brief then names the rule
  only when that symbol changes. The path must name exactly one file, and each
  name of the symbol must be in that file.
- A plain path must name at least one file or directory. It may name more than
  one.
- Never cite a line number.
- Inside a fenced block, such as a diagram in **Architecture**, a path or a
  `path:symbol` token cites code for the editing brief, with or without
  backticks. The check does not resolve fence content, so a token there that is
  not a repo path needs no allowlist entry.
- A code span that looks like a path but is not a repo path, such as a build
  output or a runtime path, goes in `.agents/feature-map/path-allowlist.txt`
  with its document.

## Keeping the map true

Update a document in the same PR when your change alters a contract, a trap, an
ownership boundary or a flow that crosses components. Most changes alter none of
these and need no update.

### Editing judgment

Judge an edit by what a future agent needs, not by what the change did. Read
only the sections and keys that cite the code you changed, and the summary. Then
answer:

1. Is anything here now wrong?
2. Did the change create a rule, trap or decision that a future agent needs and
   that the code does not show quickly?
3. Does anything in these sections no longer earn its place?
4. If you add text, what does it replace?
5. Where does this fact belong? State it in the component that owns the code and
   link it elsewhere.

No update is a normal answer. Edit only the parts the change touches. Do not
rewrite untouched parts, and do not add text only because the brief named the
document. Rewrite a whole document only in a deliberate verify pass, the one that
updates **Verified against**. **Known issues** holds real gaps, not rules that
did not fit elsewhere.

When you update a document:
- Edit or delete the text that is wrong. Do not add a paragraph about your
  change, and do not describe what your PR did.
- If you add code that no PATHS.md row covers, add a row for its component, or a
  `## Not mapped` row with the reason.
- If you add, rename or delete a contract or recipe, follow the key rules above
  and update the links that cite it.

**Verified against** records the commit on main that a person or agent last read
the whole document against: `git merge-base HEAD origin/main`, and the date. A
small fix in a code PR does not change it. `stale_docs.py --queue` lists the
components by how much of their cited code changed since that commit; start
verify passes at the top. To see the changes for one component, run
`git log <sha>..origin/main -- <the component's paths from PATHS.md>`.

## Tooling

`.agents/feature-map/check_feature_map.py` runs as the `feature-map-integrity`
pre-commit hook. It checks only what is true or false; judgment about value is in
"Editing judgment". It fails when:

- a component header, section or section order breaks the rules above, it has
  not exactly one of User experience and Callers, or its INDEX.md row does not
  repeat its summary (`--fix` writes the rows);
- a contract or recipe has no key or a duplicate key, or prose cites a contract
  by number;
- Scope lists a path, or Dependencies has a line that is not `- [[slug]]: reason`;
- prose in a component or a top-level document cites a PR number (`#1234`), or a
  code reference cites a line number;
- a backticked path or `path:symbol` reference outside a fenced block, a
  `[[slug]]` or a `[[slug#key]]` link does not resolve;
- INDEX.md or PATHS.md does not match the components, or a PATHS.md row names
  something other than component slugs outside `## Not mapped`.

It warns when a Verified-against commit is not on origin/main.

`.agents/feature-map/stale_docs.py` runs from the agent Stop hook when an agent
ends a turn. It covers the files the turn changed, and skips a document the turn
changed. When it has a brief, the hook blocks the stop once, and the next stop
runs pre-commit again to check the edits the brief led to. For each document that
cites changed code, the brief names the sections and contract or recipe keys to
read, the document's size and its growth on the branch (a renamed document counts
only its edits), and the questions in "Editing judgment".

- A `path:symbol` citation matches when a changed line sits in that symbol:
  inside the Python `def`, `class` or assignment, or the TypeScript function,
  class, method, declaration or function-valued `const`, of that name. When the
  parser cannot find the symbol, such as an interface member, any change to the
  file matches. Changes are measured from HEAD at the start of the agent's turn,
  so a commit in the turn counts. A bare file path matches any change to the
  file. A directory path does not match.
- A component that owns a changed file through PATHS.md (longest prefix wins),
  but has no part that cites the changed code, does not block the stop. When a
  brief is shown, one line lists these components.
- The brief also names changed files that no PATHS.md row covers, and gives the
  reason of the `## Not mapped` row that covers a changed file. A Not-mapped
  reason alone does not block the stop. Tests, license files and
  `__init__.py` files with no code before or after the change are skipped.
- The brief names every matching section, key and file.
- Each section or key of a document, and each file, is named once per session.
  A later change that a different contract of the same document cites is
  briefed again.

The agent decides while it still knows what it changed; usually the answer is no
update. `stale_docs.py --cited <files>` prints the contracts, recipes and
documents that cite the files.

The check catches broken references. It cannot tell when a description is wrong
while every reference still resolves. That is why the Verified-against line and
the review in VERIFYING.md exist.
