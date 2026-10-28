# Onyx docs

`documentation/` is the Onyx customer documentation (Mintlify, published at https://docs.onyx.app).

- Before you write or edit a page, read and follow `.agents/skills/docs-writing/SKILL.md` (repo root).
  It covers the reader, the sources of truth in this repo, the prose rules (ASD-STE100), the Mintlify patterns,
  screenshots, and the checks to run.
- Do not commit logos, icons, or `developers/api_reference/openapi.json`. `scripts/generate.sh` builds them from
  `web/lib/opal` and the backend. To add a logo or icon, add it to opal and map it in `scripts/generated_assets.json`.
- Run `python3 scripts/format_docs.py --write` before you commit. The `format-docs`
  pre-commit hook runs the `--check` form.
- Production docs follow the latest stable release, not `main`. A docs fix for the current release must also land
  on its `release/vX.Y` branch.
- Write for customers who self-host or use Onyx Cloud. Do not document multi-tenant operations (tenant provisioning,
  the control plane, `MULTI_TENANT`-only code). Customers cannot use them.
