# Fork changes

This repo is a **fork of [Onyx](https://github.com/onyx-dot-app/onyx)**. This file is the
authoritative list of everything we changed relative to upstream, so that pulling upstream updates
stays low-conflict and any lost change is easy to re-apply.

**Principle:** keep all fork logic in **net-new files**; touch shared upstream files as little as
possible; tag every unavoidable edit with a `FORK:` marker. To find every touchpoint in the tree:

```bash
grep -rn "FORK:" backend/onyx web/src web/lib --include='*.py' --include='*.ts' --include='*.tsx'
```

## Syncing upstream

1. Work on a branch; never commit fork changes straight to a branch that tracks upstream `main`.
2. Enable conflict-resolution memory once: `git config rerere.enabled true`.
3. Add the upstream remote once: `git remote add upstream https://github.com/onyx-dot-app/onyx.git`.
4. Prefer rebasing onto an upstream **release tag**, not raw `main`:
   `git fetch upstream --tags && git rebase <tag>`.
5. After the rebase, run the grep above + the checklist below to confirm every touchpoint survived,
   then run the verification steps in `.claude/plans/` for the affected feature.

---

## Net-new files (no conflict risk)

These exist only in the fork; upstream never touches them.

| Path | Purpose |
| --- | --- |
| `backend/onyx/connectors/monday/__init__.py` | package marker |
| `backend/onyx/connectors/monday/connector.py` | `MondayConnector` implementation |
| `backend/onyx/connectors/monday/README.md` | developer docs |
| `backend/onyx/connectors/fork_registry.py` | fork-only `FORK_CONNECTOR_CLASS_MAP` |
| `backend/tests/daily/connectors/monday/` | daily connector test |
| `docs/connectors/monday.md` | user-facing setup guide |
| `web/lib/opal/src/logos/monday.tsx` | `SvgMonday` logo |
| `FORK_CHANGES.md` | this manifest |

## Shared-file edits (conflict-prone — re-apply after each sync)

Each row is one edit to an upstream-maintained file. All carry a `FORK:` marker except where noted.

### Monday.com connector (Jira ticket AI-69)

| File | Edit | Status |
| --- | --- | --- |
| `backend/onyx/configs/constants.py` | `MONDAY = "monday"` at end of `DocumentSource` enum + entry in `DocumentSourceDescription`, both `# FORK: monday` | ✅ |
| `backend/onyx/connectors/registry.py` | one `# === FORK ===` block after the `CONNECTOR_CLASS_MAP` literal that does `CONNECTOR_CLASS_MAP.update(FORK_CONNECTOR_CLASS_MAP)` | ✅ |
| `web/src/lib/types.ts` | `Monday = "monday"  // FORK: monday` at end of `ValidSources` | ✅ |
| `web/src/lib/connectors/credentials.ts` | `MondayCredentialJson` interface + template-default + display-name entries | ✅ |
| `web/src/lib/connectors/connectors.tsx` | `monday:` entry in `connectorConfigs` | ✅ |
| `web/src/lib/sources.ts` | `SvgMonday` import + `monday` entry in `SOURCE_METADATA_MAP` | ✅ |
| `web/lib/opal/src/logos/index.ts` | `export { default as SvgMonday } ...` (one marked line) | ✅ |
| `backend/tests/utils/secret_names.py` | `MONDAY_API_TOKEN` in `TestSecret` | ✅ |

> **Why the registry is special:** instead of editing the `CONNECTOR_CLASS_MAP` dict body (which
> upstream edits on every connector PR → guaranteed conflicts), the fork adds a single merge-hook
> *after* the dict and keeps the actual mapping in `fork_registry.py`. Future fork connectors only
> edit `fork_registry.py` — no further `registry.py` churn.

> **Why enums can't use the hook:** Python `DocumentSource` and TS `ValidSources` are enums and
> can't be extended at runtime, and DB columns / derived types key off them — so these edits are
> unavoidable. Keeping them at the end of the enum + marked makes any conflict a one-line re-add.
