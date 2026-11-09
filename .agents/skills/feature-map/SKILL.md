---
name: feature-map
description: Use the Onyx feature map (.agents/feature-map/) to learn what a product surface does, the code behind it, and what a change can break. Use it before changing a feature, when reviewing a diff or PR, and when asked what a feature does or how parts connect.
---

# Onyx feature map

`.agents/feature-map/` records how Onyx works: where each responsibility lives,
how the parts connect, the rules a change can break, the design reasons, and known
issues. It does not restate the code.

## Find the component

- For new work: start at the Common tasks table in `.agents/feature-map/INDEX.md`
  and at `.agents/feature-map/CROSS-CUTTING.md`.
- From a code path: look it up in `.agents/feature-map/PATHS.md`. The longest
  matching prefix wins. A path under `## Not mapped` has no component. A path
  that no row covers is unmapped: say so, and read the nearest code and tests
  yourself.
- Before you trust a name, read `.agents/feature-map/GLOSSARY.md`. Onyx uses words
  such as Persona, Tool, turn and SearchDoc in more than one sense.

## Before you change code

Read the component document under `.agents/feature-map/components/`.
**User experience** (or **Callers**, for a component that other code builds on)
says what the component must do for the people and code that use it. **Contracts and traps**
come next: these are the rules a change can break without a failing test.
**Recipes** show how to do common tasks. Follow the `[[component]]` links in
**Dependencies** for each area your change reaches.

## When you review a diff or PR

Follow `.agents/feature-map/VERIFYING.md` step by step.

## Keep the map true

When you end a turn, the Stop hook may block once with an editing brief. It names
the sections and keys that cite the code you changed. Read only those and the
summary, and answer the questions in "Editing judgment" in
`.agents/feature-map/README.md`. No update is a normal answer. Do not rewrite
parts the change does not touch. The full rules are in "Keeping the map true".
