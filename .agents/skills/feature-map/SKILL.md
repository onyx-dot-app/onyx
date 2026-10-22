---
name: feature-map
description: Use the Onyx feature map (.agents/feature-map/) to learn what a product surface does, the code behind it, and what a change can break. Use it before changing a feature, when reviewing a diff or PR, and when asked what a feature does or how parts connect.
---

# Onyx feature map

`.agents/feature-map/` describes every Onyx product surface as one component
document: what the user sees, the code paths, the data model, the contracts, what
else a change touches, how to verify it, and the known traps.

## Find the component

- From a code path: look it up in `.agents/feature-map/PATHS.md`. The longest
  matching prefix wins. A path with no row is unmapped: say so, and read the
  nearest code and tests yourself.
- From a feature name: browse `.agents/feature-map/INDEX.md`.
- Before you trust a name, read `.agents/feature-map/GLOSSARY.md`. Onyx uses words
  such as Persona, Tool, turn and SearchDoc in more than one sense.

## Before you change code

Read the component document under `.agents/feature-map/components/`:

- §1 and §4: what the code must do.
- §5 Contracts and invariants: the rules a change can break without any test
  failing.
- §7 Blast radius: the other files to check for your kind of change.
- §9 Footguns: the known traps.

Follow the `[[component]]` links in §6 for any area your change reaches into.

## When you review a diff or PR

Follow `.agents/feature-map/VERIFYING.md` step by step. Check every invariant in §5
of each touched component and state a verdict for each one. Report what you could
not verify.

## Keep the map true

If your change alters behaviour that a component document describes, update that
document in the same PR. If you add a code path, add its row to `PATHS.md`. Cite
only paths and symbols that exist; a wrong reference is worse than none.
