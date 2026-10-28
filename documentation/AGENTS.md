# Onyx docs

This repo is the Onyx customer documentation (Mintlify, published at https://docs.onyx.app).

- Before you write or edit a page, read and follow `.agents/skills/docs-writing/SKILL.md`.
  It covers the reader, the sources of truth in the onyx repo, the prose rules (ASD-STE100), the Mintlify patterns,
  screenshots, and the checks to run.
- Skills live in `.agents/skills/`. `.claude/skills`, `.cursor/skills`, and `.codex/skills`
  are symlinks to it.
- Run `python3 scripts/format_docs.py --write` before you commit. The `format-docs`
  pre-commit hook runs the `--check` form.
