# Gate inventory

Every hook definition in `.pre-commit-config.yaml` requires approval to change.
Protect the code each hook runs. For a remote hook, protect the configured
revision. For a uv-run hook, protect its package pin and lock entry. For a
local hook, protect its invocation, scripts and gate policy files.
The table records where these inputs and exception definitions live.

| Hook | Runtime | Definition and exceptions | Scope |
| --- | --- | --- | --- |
| uv-sync | remote | `pyproject.toml`, `uv.lock` | Dependency sync. Package and lock changes are outside the gate. |
| pip-compile | remote | `tools/requirements/build-constraints.in` and generated constraints | Dependency sync. Generated data and dependency pins are outside the gate. |
| uv-lock | remote | `pyproject.toml`, `uv.lock` | Dependency sync. Package and lock changes are outside the gate. |
| uv-export default.txt | remote | `pyproject.toml`, `uv.lock`, `backend/requirements/default.txt` | Generated dependency file. Outside the gate. |
| uv-export dev.txt | remote | `pyproject.toml`, `uv.lock`, `backend/requirements/dev.txt` | Generated dependency file. Outside the gate. |
| uv-export ee.txt | remote | `pyproject.toml`, `uv.lock`, `backend/requirements/ee.txt` | Generated dependency file. Outside the gate. |
| uv-export model_server.txt | remote | `pyproject.toml`, `uv.lock`, `backend/requirements/model_server.txt` | Generated dependency file. Outside the gate. |
| check-getattr | uv-run | `onyx-devtools` wheel, `# ods: ignore[getattr]` | Covered. |
| check-lazy-imports | uv-run | `onyx-devtools` wheel. No inline waiver. | Covered. |
| docker-compose-sync | uv-run | `onyx-devtools` wheel and deployment templates. No inline waiver. | Wheel covered. Generated deployment files are outside the gate. |
| ty | uv-run | `[tool.ty]`, `ty.toml`, `# ty: ignore[rule]`, `# type: ignore` | Covered. |
| ruff | uv-run | `[tool.ruff]`, `ruff.toml`, `.ruff.toml`, `noqa`, `ruff: ignore` and `ruff: disable/enable` | Covered. |
| ruff-format | uv-run | Ruff config and `# fmt: skip/off/on` | Config covered. Formatting waivers are outside the gate. |
| terraform-fmt | uv-run | `onyx-devtools` wheel. No inline waiver. | Wheel covered. Formatting is outside the gate. |
| terraform-public-safe | uv-run | `onyx-devtools` wheel, `# public-safe: ok` | Wheel covered. Deployment waivers are outside the gate. |
| typescript-check | uv-run | `onyx-devtools` wheel, `web/tools/type-check/`, the `types:check` package script, TypeScript configs, `web/.type-coverage-baseline.yaml`, `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck` | Covered. |
| zizmor | uv-run | Zizmor package pin and `# zizmor: ignore[rule]` | Package covered. Inline waivers and tool config are outside the gate. |
| check-added-large-files | remote | Hook sets file-size limit. Git LFS files can be exempt. | Hook covered. LFS settings are outside the gate. |
| check-yaml | remote | Hook sets parser options. No inline waiver. | Hook covered. |
| actionlint | remote | Workflow syntax and `.github/actionlint.yaml` if present | Workflow syntax lint is outside the gate. The two gate workflows are covered. |
| shellcheck | remote | Hook options and `# shellcheck disable=CODE` | Shell lint is outside the gate. |
| golangci-lint | remote | Module `.golangci.yml` and `//nolint` | Go lint is outside the gate. |
| ripsecrets | remote | Hook arguments and `# pragma: allowlist secret` | Secret scanning has its own review policy. Its waivers are outside the gate. |
| terraform_validate | remote | Terraform modules and hook options. No inline waiver. | Deployment validation is outside the gate. |
| prettier | system | Formatting config and `prettier-ignore` | Formatting is outside the gate. |
| helm-release | python | `tools/helm/check_release.py`, chart versions and release notes | Script covered. Release data is outside the gate. |
| microvm-python-stubs | python | `backend/onyx/microvm/generated/regenerate.sh`, proto inputs | Script covered. Generated code is outside the gate. |
| i18n-copy-changes | system | `tools/i18n/check_copy_changes.py` and translation files | Script covered. Translation text is outside the gate. |
| build-constraints-drift | system | `tools/requirements/check_build_constraints.py` and build pins | Script covered. Dependency pins outside the lint-tool groups are outside the gate. |
| migration-determinism | system | `backend/scripts/check_migration_determinism.py`, `migration-determinism: allow` | Covered. |
| migration-design | system | `backend/lint/check_migration_design.py`, `# migration-design: allow <rule> - <reason>` | Covered. |
| celery-task-expires | system | `backend/lint/check_celery_task_expires.py`, `# celery-expires: allow (<reason>)` | Covered. |
| celery-task-allowlist | system | `backend/lint/check_celery_task_allowlist.py`, `celery_task_allowlist.txt` | Covered. |
| no-http-exception | system | `backend/lint/check_no_http_exception.py`, count baseline, `# http-exception: allow <reason>` | Covered. |
| test-flakes | python | `backend/lint/check_test_flakes.py`, sleep and skip baselines, `test-flakes: allow <reason>` in Python and Playwright comments | Covered. Native test skip reasons remain part of the test API. |
| no-response-model | system | `backend/lint/check_no_response_model.py`, count baseline, `# no-response-model: allow <reason>` | Covered. |
| no-direct-redis | system | `backend/lint/check_no_direct_redis.py`, count baseline, `no-direct-redis: allow` | Covered. |
| db-ops-outside-db | system | `backend/lint/check_db_ops_outside_db.py`, count baseline, `# db-ops-outside-db: allow <reason>` | Covered. |
| import-boundaries | system | `backend/lint/check_import_boundaries.py`, `import_boundaries.toml` and its `[[contract.exception]]` entries | Covered. |
| feature-map-integrity | system | `.agents/feature-map/check_feature_map.py` and map documents | Script covered. Map content is outside the gate. |
| env-drift-baseline | system | `backend/scripts/env_inventory.py` and `backend/scripts/env_inventory_baseline.txt` | Covered. |
| bun-install | system | Web package manifests and lockfile | Dependency install. Outside the gate. |
| bun-install-check | system | Web package manifests and lockfile | Dependency sync. Outside the gate. |
| opal-css-rebuild | system | Opal CSS, tokens, `web/lib/opal/scripts/bundle-css.mjs`, and `build:tokens` | Commands covered. Generated build data is outside the gate. |
| clear-web-build-cache | system | Web build config and cache | Local maintenance. Outside the gate. |
| root-bun-install | system | Root workspace manifests and lockfile | Dependency install. Outside the gate. |
| root-bun-install-check | system | Root workspace manifests and lockfile | Dependency sync. Outside the gate. |
| oxfmt | system | Formatter config and `oxfmt-ignore` | Formatting is outside the gate. |
| oxlint | system | `.oxlintrc.json`, `web/tools/oxlint/` including anti-slop, i18n, navigation and Opal, the `oxlint` package script, `oxlint-disable/enable` and ESLint spellings | Covered. Package and lock changes are outside the gate. |
| widget-typescript-check | system | Widget TS configs and `@ts-*` directives | Covered. |
| examples-widget-typescript-check | system | Example widget TS config and `@ts-*` directives | Covered. |
| shared-typescript-check | system | Shared library TS configs and `@ts-*` directives | Covered. |
| desktop-rust-fmt | system | Rustfmt settings and `rustfmt::skip` | Formatting is outside the gate. |
| desktop-rust-clippy | system | Cargo and Clippy config, `#[allow(...)]`, `#[expect(...)]` | Rust lint is outside the gate. |
| desktop-v2-rust-fmt | system | Rustfmt settings and `rustfmt::skip` | Formatting is outside the gate. |
| desktop-v2-rust-clippy | system | Cargo and Clippy config, `#[allow(...)]`, `#[expect(...)]` | Rust lint is outside the gate. |
| mobile-bun-install | system | Mobile manifest and lockfile | Dependency install. Outside the gate. |
| mobile-bun-install-check | system | Mobile manifest and lockfile | Dependency sync. Outside the gate. |
| mobile-typescript-check | system | Mobile TS config and `@ts-*` directives | Covered. |
| mobile-lint | system | `mobile/eslint.config.js`, `eslint-disable/enable` | Covered. |
| mobile-format | system | `mobile/.prettierrc.json`, `prettier-ignore` | Formatting is outside the gate. |
| format-docs | system | `documentation/scripts/format_docs.py` | Script covered. Formatting is outside the gate. |
| docs-connector-grid | system | `documentation/scripts/build_connector_grid.py`, generated grid | Script covered. Generated grid is outside the gate. |
| require-verification-trailer | system | `.agents/hooks/verification_trailer.py`, `Verified-by: none (reason)` | Script covered. Local commit policy is outside the gate. |
| record-verification-trailer | system | `.agents/hooks/verification_trailer.py` | Script covered. Local commit policy is outside the gate. |

The guard covers its own workflow, the PR quality workflow, and CODEOWNERS.
It also covers `.greptile/config.json`, `.greptile/files.json`,
`.greptile/rules.md`, and `cubic.yaml`. These review tools use config and
review comments. They have no repository-controlled inline code waiver.
No pre-commit hook runs ODS from `tools/ods/`. ODS hooks install the
published `onyx-devtools` wheel from the `ods` group and `uv.lock`. The Go CI
workflow builds ODS from source for its own coverage job. That separate workflow
and other test-suite policies are outside this lint gate.
