# Gate inventory

Every hook definition in `.pre-commit-config.yaml` requires approval to change.
The table records coverage of the files and exceptions used by each hook.

| Hook | Definition and exceptions | Scope |
| --- | --- | --- |
| uv-sync | `pyproject.toml`, `uv.lock` | Dependency sync. Package and lock changes are outside the gate. |
| pip-compile | `tools/requirements/build-constraints.in` and generated constraints | Dependency sync. Generated data and dependency pins are outside the gate. |
| uv-lock | `pyproject.toml`, `uv.lock` | Dependency sync. Package and lock changes are outside the gate. |
| uv-export default.txt | `pyproject.toml`, `uv.lock`, `backend/requirements/default.txt` | Generated dependency file. Outside the gate. |
| uv-export dev.txt | `pyproject.toml`, `uv.lock`, `backend/requirements/dev.txt` | Generated dependency file. Outside the gate. |
| uv-export ee.txt | `pyproject.toml`, `uv.lock`, `backend/requirements/ee.txt` | Generated dependency file. Outside the gate. |
| uv-export model_server.txt | `pyproject.toml`, `uv.lock`, `backend/requirements/model_server.txt` | Generated dependency file. Outside the gate. |
| check-getattr | `tools/ods/cmd/check_getattr.go`, `tools/ods/internal/pycheck/`, `# ods: ignore[getattr]` | Covered. |
| check-lazy-imports | `tools/ods/cmd/check_lazy_imports.go`, `tools/ods/internal/lazyimports/`. No inline waiver. | Covered. |
| docker-compose-sync | ODS Compose generator and deployment templates. No inline waiver. | Generated deployment files are outside the gate. |
| ty | `[tool.ty]`, `ty.toml`, `# ty: ignore[rule]`, `# type: ignore` | Covered. |
| ruff | `[tool.ruff]`, `ruff.toml`, `.ruff.toml`, `noqa`, `ruff: ignore` and `ruff: disable/enable` | Covered. |
| ruff-format | Ruff config and `# fmt: skip/off/on` | Config covered. Formatting waivers are outside the gate. |
| terraform-fmt | ODS Terraform formatter. No inline waiver. | Formatting is outside the gate. |
| terraform-public-safe | ODS Terraform lint rules in `tools/ods/` | Deployment policy is outside this gate. |
| typescript-check | `tools/ods/cmd/type_coverage.go`, `coverage_gate.go`, `tools/ods/internal/typecoverage/` and `coverage/`, `web/tools/type-check/`, the `types:check` package script, TypeScript configs, `web/.type-coverage-baseline.yaml`, `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck` | Covered. |
| zizmor | Tool pin and config. `# zizmor: ignore[rule]` | Workflow security has its own review policy. Inline waivers and tool config are outside the gate. |
| check-added-large-files | Hook sets file-size limit. Git LFS files can be exempt. | Hook covered. LFS settings are outside the gate. |
| check-yaml | Hook sets parser options. No inline waiver. | Hook covered. |
| actionlint | Workflow syntax and `.github/actionlint.yaml` if present | Workflow syntax lint is outside the gate. The two gate workflows are covered. |
| shellcheck | Hook options and `# shellcheck disable=CODE` | Shell lint is outside the gate. |
| golangci-lint | Module `.golangci.yml` and `//nolint` | Go lint is outside the gate. |
| ripsecrets | Hook arguments and `# pragma: allowlist secret` | Secret scanning has its own review policy. Its waivers are outside the gate. |
| terraform_validate | Terraform modules and hook options. No inline waiver. | Deployment validation is outside the gate. |
| prettier | Formatting config and `prettier-ignore` | Formatting is outside the gate. |
| helm-release | `tools/helm/check_release.py`, chart versions and release notes | Release validation is outside the gate. |
| microvm-python-stubs | `backend/onyx/microvm/generated/regenerate.sh`, proto inputs | Generated code is outside the gate. |
| i18n-copy-changes | `tools/i18n/check_copy_changes.py` and translation files | Translation checks are outside the gate. |
| build-constraints-drift | `tools/requirements/check_build_constraints.py` and build pins | Dependency drift is outside the gate. |
| migration-determinism | `backend/scripts/check_migration_determinism.py`, `migration-determinism: allow` | Covered. |
| migration-design | `backend/lint/check_migration_design.py`, `# migration-design: allow <rule> - <reason>` | Covered. |
| celery-task-expires | `backend/lint/check_celery_task_expires.py`, `# celery-expires: allow (<reason>)` | Covered. |
| celery-task-allowlist | `backend/lint/check_celery_task_allowlist.py`, `celery_task_allowlist.txt` | Covered. |
| no-http-exception | `backend/lint/check_no_http_exception.py`, count baseline, `# http-exception: allow <reason>` | Covered. |
| test-flakes | `backend/lint/check_test_flakes.py`, sleep and skip baselines, `test-flakes: allow <reason>` in Python and Playwright comments | Covered. Native test skip reasons remain part of the test API. |
| no-response-model | `backend/lint/check_no_response_model.py`, count baseline, `# no-response-model: allow <reason>` | Covered. |
| no-direct-redis | `backend/lint/check_no_direct_redis.py`, count baseline, `no-direct-redis: allow` | Covered. |
| db-ops-outside-db | `backend/lint/check_db_ops_outside_db.py`, count baseline, `# db-ops-outside-db: allow <reason>` | Covered. |
| import-boundaries | `backend/lint/check_import_boundaries.py`, `import_boundaries.toml` and its `[[contract.exception]]` entries | Covered. |
| feature-map-integrity | `.agents/feature-map/check_feature_map.py` and map documents | Documentation validation is outside the gate. |
| env-drift-baseline | `backend/scripts/env_inventory.py` and `backend/scripts/env_inventory_baseline.txt` | Covered. |
| bun-install | Web package manifests and lockfile | Dependency install. Outside the gate. |
| bun-install-check | Web package manifests and lockfile | Dependency sync. Outside the gate. |
| opal-css-rebuild | Opal CSS, tokens, bundler | Build maintenance. Outside the gate. |
| clear-web-build-cache | Web build config and cache | Local maintenance. Outside the gate. |
| root-bun-install | Root workspace manifests and lockfile | Dependency install. Outside the gate. |
| root-bun-install-check | Root workspace manifests and lockfile | Dependency sync. Outside the gate. |
| oxfmt | Formatter config and `oxfmt-ignore` | Formatting is outside the gate. |
| oxlint | `.oxlintrc.json`, `web/tools/oxlint/` including anti-slop, i18n, navigation and Opal, the `oxlint` package script, `oxlint-disable/enable` and ESLint spellings | Covered. Package and lock changes are outside the gate. |
| widget-typescript-check | Widget TS configs and `@ts-*` directives | Covered. |
| examples-widget-typescript-check | Example widget TS config and `@ts-*` directives | Covered. |
| shared-typescript-check | Shared library TS configs and `@ts-*` directives | Covered. |
| desktop-rust-fmt | Rustfmt settings and `rustfmt::skip` | Formatting is outside the gate. |
| desktop-rust-clippy | Cargo and Clippy config, `#[allow(...)]`, `#[expect(...)]` | Rust lint is outside the gate. |
| desktop-v2-rust-fmt | Rustfmt settings and `rustfmt::skip` | Formatting is outside the gate. |
| desktop-v2-rust-clippy | Cargo and Clippy config, `#[allow(...)]`, `#[expect(...)]` | Rust lint is outside the gate. |
| mobile-bun-install | Mobile manifest and lockfile | Dependency install. Outside the gate. |
| mobile-bun-install-check | Mobile manifest and lockfile | Dependency sync. Outside the gate. |
| mobile-typescript-check | Mobile TS config and `@ts-*` directives | Covered. |
| mobile-lint | `mobile/eslint.config.js`, `eslint-disable/enable` | Covered. |
| mobile-format | `mobile/.prettierrc.json`, `prettier-ignore` | Formatting is outside the gate. |
| format-docs | `documentation/scripts/format_docs.py` | Formatting is outside the gate. |
| docs-connector-grid | `documentation/scripts/build_connector_grid.py`, generated grid | Documentation validation is outside the gate. |
| require-verification-trailer | `.agents/hooks/verification_trailer.py`, `Verified-by: none (reason)` | Local commit process is outside the gate. |
| record-verification-trailer | `.agents/hooks/verification_trailer.py` | Local commit process is outside the gate. |

The guard covers its own workflow, the PR quality workflow, and CODEOWNERS.
It also covers `.greptile/config.json`, `.greptile/files.json`,
`.greptile/rules.md`, and `cubic.yaml`. These review tools use config and
review comments. They have no repository-controlled inline code waiver.
Other CI workflows and test-suite policies are outside this lint gate.
