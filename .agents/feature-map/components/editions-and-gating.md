# Editions and Gating

> The dispatcher that decides, at import time, whether a call resolves to the
> Community implementation or the Enterprise one, plus the license, feature-flag,
> and per-action gating layers built on top of it. Its central fact is
> counter-intuitive: in a standard deployment, Enterprise code is the default,
> not the exception.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** platform
**Edition:** CE dispatcher, EE implementations and license/billing server
**Owns:**
`backend/onyx/utils/variable_functionality.py`, `backend/onyx/feature_flags/`
(`interface.py`, `factory.py`, `flags.py`, `feature_flags_keys.py`),
`backend/onyx/db/gated_app.py`, `backend/onyx/server/settings/` (`api.py`,
`store.py`, `models.py`, `tier_order.py`), `backend/ee/onyx/feature_flags/`
(`factory.py`, `posthog_provider.py`), `backend/ee/onyx/server/license/`
(`api.py`, `models.py`), `backend/ee/onyx/utils/tier.py`,
`backend/ee/onyx/server/middleware/license_enforcement.py`, `backend/Dockerfile`

---

## 1. What the user experiences

An operator who clones the repository and runs a standard build with no license
still gets **Enterprise code running underneath**, because
`backend/Dockerfile:COPY --chown=onyx:onyx ./ee /app/ee` ships the `ee` package
in every standard image, and
`backend/onyx/utils/variable_functionality.py:set_is_ee_if_available` loads it
whenever the build ships it. No environment variable turns Enterprise code off.
What changes with a license is not which code runs but which
paths are unlocked: `backend/ee/onyx/server/middleware/license_enforcement.py`
blocks or allows requests, and `backend/ee/onyx/utils/tier.py:get_tier` decides
which tier-gated features respond instead of 402/403.

For a self-hosted operator, the visible progression is: no license, run as
Community (`Tier.COMMUNITY` in `backend/onyx/server/settings/models.py`);
upload or claim a license via the `/license` endpoints
(`backend/ee/onyx/server/license/api.py`), and previously blocked admin
surfaces, seat limits, and tier-gated features unlock. A cloud (`MULTI_TENANT`)
deployment still registers the license routes. `GET /license`, `GET /license/seats`,
and `POST /license/refresh` are callable only for ungated tenants. Claim, upload,
delete, and downgrade reject cloud requests with a `MULTI_TENANT` check. Gating there is
external, through the control plane:
`backend/ee/onyx/server/middleware/tenant_tracking.py` calls
`backend/ee/onyx/server/tenants/product_gating.py:is_tenant_gated`. For a gated
tenant it returns 402 (`SUBSCRIPTION_INACTIVE`) before the handler runs. `/license`
is not in `backend/ee/onyx/configs/multi_tenant_gating_config.py:MULTI_TENANT_GATING_ALLOWED_PREFIXES`.
`backend/ee/onyx/server/settings/api.py:apply_license_status_to_settings` sets
`ee_features_enabled` to true for cloud.

An admin building a custom OpenAPI action or MCP tool also sees per-action
gating: each action defaults to a policy (`ALWAYS`, `ASK`, `DENY` in
`backend/onyx/db/enums.py:EndpointPolicy`) resolved through the `gated_app`
tables, independent of CE/EE at all.

---

## 2. Surfaces

### Environment variables

| Variable | Read in | Default | Effect |
|---|---|---|---|
| `MULTI_TENANT` | `backend/shared_configs/configs.py` | `false` | Cloud mode. Selects control-plane gating (`add_api_server_tenant_id_middleware`) over the self-hosted license middleware in `backend/ee/onyx/main.py:get_application`. Also gates whether `backend/onyx/feature_flags/factory.py:get_default_feature_flag_provider` even attempts the PostHog provider. |

No environment variable selects the edition. On a self-hosted deployment, none
turns license enforcement off.
The build decides the edition (`variable_functionality.py:is_ee_available`, §4.1),
and the license decides the tier (§4.4).

### License endpoints (`backend/ee/onyx/server/license/api.py`, router prefix `/license`, self-hosted only)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/license` | `get_license_status` | Current license and seat usage. |
| GET | `/license/seats` | `get_seat_usage` | Seat usage detail. |
| POST | `/license/claim` | `claim_license` | Exchanges a Stripe checkout session, or reclaims, via the cloud data plane. Rejects on `MULTI_TENANT`. |
| POST | `/license/upload` | `upload_license` | Manual signed license file upload, for air-gapped deployments. Rejects on `MULTI_TENANT`. |
| POST | `/license/refresh` | `refresh_license_cache_endpoint` | Re-reads the local DB cache; does not contact the control plane. |
| DELETE | `/license` | `delete_license` | Rejects on `MULTI_TENANT`. |
| POST | `/license/downgrade` | `downgrade_to_community` | Drops the deployment to the Community tier and deletes the license. See [[billing]] §4.5. Rejects on `MULTI_TENANT`. |

All handlers gate on `require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)`
and are sync `def` (not `async def`) because the work underneath is blocking
(`requests` calls, sync SQLAlchemy, RSA verification, Redis); see the module
docstring in `backend/ee/onyx/server/license/api.py`.

### Settings endpoints (`backend/onyx/server/settings/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| PATCH | `/admin/settings` | `admin_patch_settings` | Reads `global_version.is_ee_version()` to decide whether to call `ee.onyx.utils.tier.get_tier()` or default to `Tier.COMMUNITY`. Merges only the fields the caller sent (`model_fields_set`), under `settings_write_lock()`. |

### Feature flags

`backend/onyx/feature_flags/factory.py:get_default_feature_flag_provider` is
the single entry point callers use; it is not itself a versioned symbol. It
calls `fetch_versioned_implementation_with_fallback` for
`onyx.feature_flags.factory.get_posthog_feature_flag_provider`, but only when
`MULTI_TENANT or DEV_MODE`; otherwise it returns
`NoOpFeatureFlagProvider()` directly. `backend/onyx/feature_flags/flags.py` and
`backend/onyx/feature_flags/feature_flags_keys.py` are currently empty
scaffolding; flag keys are defined ad hoc at their call sites (see
`backend/onyx/server/features/build/utils.py:ONYX_CRAFT_ENABLED_FLAG`).

### Gated apps (`backend/onyx/db/gated_app.py`)

Not an edition boundary. `GatedApp` is the identity row shared by every gated
target (`GatedAppKind.EXTERNAL_APP` or `MCP_SERVER`, in `backend/onyx/db/enums.py`);
`GatedActionPolicy` stores per-action overrides (`EndpointPolicy.ALWAYS` /
`ASK` / `DENY`). Consumers: `backend/onyx/server/features/mcp/api.py`,
`backend/onyx/server/features/build/external_apps/api.py`,
`backend/onyx/sandbox_proxy/addons/gate.py`, and
`backend/onyx/external_apps/matching/engine.py`.

---

## 3. Data model

This component is mostly code dispatch, not data, with two exceptions:

- `GatedApp` / `GatedActionPolicy` (`backend/onyx/db/models.py`, CE): the
  per-action approval policy, keyed by `(kind, target_id)` via
  `gated_app.py:_target_column`.
- License metadata is stored and cached by EE code
  (`backend/ee/onyx/db/license.py:get_license_metadata`,
  `get_cached_license_metadata`, `refresh_license_cache`), not owned by this
  document; see [[cc-pairs-and-credentials]] for the adjacent encrypted-secret
  storage pattern this component's dispatch also protects.

---

## 4. How it works

### 4.1 The resolution flow

```
process start (onyx.main, or one of background/celery/versioned_apps/*.py)
  └─ set_is_ee_if_available()                 onyx/utils/variable_functionality.py
       if is_ee_available():                     (find_spec("ee.onyx") names a real package)
         global_version.set_ee()
       else:
         (stays CE; only reachable in a build without the `ee.onyx` package)

later, at any call site:
  fetch_versioned_implementation(module, attribute)
    is_ee = global_version.is_ee_version()
    module_full = f"ee.{module}" if is_ee else module
    import module_full, return getattr(module_full, attribute)
    on ModuleNotFoundError while is_ee:
      if "ee.onyx" not in the error -> re-raise (a real missing dependency, not a version fallback)
      else -> import the plain `module` and return its attribute (CE fallback)
    on ModuleNotFoundError while not is_ee -> raise
```

Because `backend/Dockerfile` always copies `./ee` into the image
(`COPY --chown=onyx:onyx ./ee /app/ee`), the "on ModuleNotFoundError while
is_ee" branch is not the path a standard deployment takes: `ee.<module>`
resolves successfully essentially every time EE is set, which per the flow
above is every build that ships `backend/ee/onyx`. The CE branch above
(`module_full = module`, no `ee.` prefix) is reached only when
`global_version.is_ee_version()` is `False`, which requires a build without
the `ee.onyx` package. `variable_functionality.py:is_ee_available` calls
`importlib.util.find_spec("ee.onyx")` and returns false in three cases: there
is no `ee` package (`find_spec` raises `ModuleNotFoundError`), there is a bare
`ee` package with no `onyx` inside (the MIT-only mirror, per the function's
docstring), or `ee/onyx` is a directory with no `__init__.py` (a namespace
package, whose spec has no origin). Such a build resolves every versioned
symbol to CE.

`set_is_ee_if_available()` runs at module level (not lazily) in
`backend/onyx/main.py` (before `app = fetch_versioned_implementation(module="onyx.main", attribute="get_application")`)
and in every `backend/onyx/background/celery/versioned_apps/*.py`
(`beat.py`, `client.py`, `docfetching.py`, `docprocessing.py`, `heavy.py`,
`light.py`, `monitoring.py`, `primary.py`, `scheduled_tasks.py`,
`user_file_processing.py`). Each process decides its own EE-ness once, on
import, and `global_version` is a plain in-process singleton
(`OnyxVersion`, `variable_functionality.py`), so it does not span processes:
a mixed deployment where the API server and a Celery worker were built from
different image variants can legitimately disagree.

`ee.onyx.main.get_application` additionally calls `global_version.set_ee()`
directly at the top of its body, both belt-and-suspenders and a signal that
merely reaching that function already implies EE.

### 4.2 The two dispatch helpers, and why they differ

- `fetch_versioned_implementation(module, attribute)`
  (`variable_functionality.py:fetch_versioned_implementation`, `lru_cache`d):
  raises if the symbol cannot be resolved on either side. Used where an
  implementation must exist for the process to function, for example
  `onyx.main.get_application` itself, or `backend/onyx/access/access.py`'s
  several `versioned_*_fn` lookups for `_get_access_for_document`,
  `_get_access_for_documents`, and the ACL-for-user function. A missing
  symbol here is a hard startup or request failure, not silent.
- `fetch_versioned_implementation_with_fallback(module, attribute, fallback)`
  (`variable_functionality.py:fetch_versioned_implementation_with_fallback`):
  swallows any exception and returns `fallback`. Used by
  `backend/onyx/feature_flags/factory.py:get_default_feature_flag_provider`
  to fall back to `NoOpFeatureFlagProvider()` if the PostHog factory cannot be
  imported.
- `fetch_ee_implementation_or_noop(module, attribute, noop_return_value)`
  (`variable_functionality.py:fetch_ee_implementation_or_noop`): checks
  `global_version.is_ee_version()` **first**, before attempting any import.
  If not EE, it returns a no-op closure, without ever attempting to import
  `ee.<module>`. The closure type depends on `inspect.iscoroutinefunction(noop_return_value)`.
  A sync closure ignores every argument and returns `noop_return_value`. An async
  closure calls and awaits `noop_return_value(*args, **kwargs)`, so the fallback
  can run code. If EE, it delegates to
  `fetch_versioned_implementation` and re-raises on failure (an EE process
  that cannot load an EE-only symbol is a real error, not a fallback case).
  Also used for the tier guards in `backend/ee/onyx/utils/tier.py`
  (`require_business_tier_for_sync_access`, `require_business_tier_for_connector_group_restrictions`,
  `require_business_tier_for_multi_sso`), which are no-ops in CE. Used at
  `backend/onyx/context/search/pipeline.py` for
  `onyx.external_permissions.post_query_censoring._post_query_chunk_censoring`,
  where there is **no CE module at that path at all**
  (`backend/onyx/external_permissions/` does not exist; only
  `backend/ee/onyx/external_permissions/post_query_censoring.py` does). See
  §5 and §9 for the safety implication.

### 4.3 Feature flags

`get_default_feature_flag_provider()` (`backend/onyx/feature_flags/factory.py`)
returns `NoOpFeatureFlagProvider` (`backend/onyx/feature_flags/interface.py`,
always answers `False`) unless `MULTI_TENANT or DEV_MODE`, in which case it
attempts the EE PostHog provider
(`backend/ee/onyx/feature_flags/factory.py:get_posthog_feature_flag_provider`),
itself falling back to `NoOpFeatureFlagProvider` if `posthog` (the client) is
`None`, for example no `POSTHOG_API_KEY` configured locally.

Two shapes of flag exist, both on `FeatureFlagProvider`
(`backend/onyx/feature_flags/interface.py`):
- `feature_enabled_for_user_tenant`: evaluates a flag for one user. It has no
  default parameter. An unresolvable flag answers whatever the provider's base
  `feature_enabled` returns (`False` for `NoOpFeatureFlagProvider`).
- `feature_variant_for_tenant`: reads a multivariate flag for the whole tenant.
  The base class and `NoOpFeatureFlagProvider` return `None`. The PostHog
  provider keys the flag on `tenant_id`
  (`backend/ee/onyx/feature_flags/posthog_provider.py`).

### 4.4 Licensing

Self-hosted only. `/license/claim` and `/license/upload`
(`backend/ee/onyx/server/license/api.py`) both reject on `MULTI_TENANT`, since
cloud licensing is driven by the control plane and the `gated_tenants` Redis
key instead. `backend/ee/onyx/server/middleware/license_enforcement.py`
enforces license state (`GATED_ACCESS`, seat limits) on every self-hosted
deployment; MULTI_TENANT
deployments get `add_api_server_tenant_id_middleware` instead
(`backend/ee/onyx/main.py:get_application`). Whether EE *features* (as
opposed to EE *code*) are actually unlocked is a separate question, answered
by `backend/ee/onyx/utils/tier.py:get_tier` and, for the UI, by the
`ee_features_enabled` field that
`backend/ee/onyx/server/settings/api.py:apply_license_status_to_settings` sets:
EE code loading is necessary but not sufficient for a paid feature to respond.
With no license, `tier.py:_self_hosted_tier` resolves `Tier.COMMUNITY`.

`GET /settings` reports the license state through
`backend/ee/onyx/server/settings/api.py:apply_license_status_to_settings`
(self-hosted). With no license in the cache or the DB, it sets
`ee_features_enabled` to false and `tier` to `Tier.COMMUNITY`. It sets
`application_status` to `GATED_ACCESS` only when a perm-synced cc-pair exists
(`_has_perm_synced_cc_pairs`, which calls
`backend/onyx/db/connector_credential_pair.py:has_perm_synced_cc_pairs`). A DB
error in that check counts as true, so it fails closed. The Community downgrade
([[billing]] §4.5) leaves no perm-synced pair, so a downgraded deployment is
not gated.

---

## 5. Contracts and invariants

1. **EE code loading is the default in a standard deployment.** A CE-only
   code path (`global_version.is_ee_version() is False`) is not the normal
   case; it requires a build without the `ee.onyx` package (§4.1). No
   environment variable turns EE code off. Do not write or review code as if CE resolution is the
   common path; assume `ee.<module>` unless proven otherwise for the target
   deployment.
2. **A CE stub that "does nothing" is not evidence Onyx does nothing.** The
   CE implementation of a versioned symbol may be an intentional no-op
   (`backend/onyx/utils/encryption.py:_encrypt_string` returns the input
   unchanged) whose real behaviour lives only in `backend/ee/onyx/...` and
   which is the version actually loaded by default. See §9.
3. **A `fetch_ee_implementation_or_noop` no-op fallback must never widen
   access or skip a security control.** It may only skip *additional*
   filtering layered on top of a control that is enforced unconditionally
   elsewhere. `onyx.external_permissions.post_query_censoring` is safe under
   this rule only because document-level ACL enforcement
   (`backend/onyx/access/access.py`, `build_access_filters_for_user`) runs in
   CE regardless of edition; the EE censoring adds field-level filtering on
   top for specific sync-permission connectors (Salesforce, etc.). If a
   future no-op fallback ever guards the *only* enforcement of a control,
   that is a bug, not an EE/CE split.
4. **Versioned symbols must keep identical signatures on both sides.** There
   is no type-check across the `ee.<module>` boundary; a signature mismatch
   fails at import or call time in production, not in CI type-checking. The
   `# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation`
   comments (e.g. above `_encrypt_string` and `_decrypt_bytes` in both
   `backend/onyx/utils/encryption.py` and `backend/ee/onyx/utils/encryption.py`)
   exist because these symbols are invisible to static "who calls this"
   analysis; `importlib.import_module` plus `getattr` is a string-keyed
   lookup, not a normal import graph edge.
5. **Symbols reached only through dispatch must not be deleted as dead
   code.** Any cleanup pass (manual or automated) that flags a
   `_encrypt_string`, `_get_access_for_document`, or similar function as
   unreferenced is wrong; grep for the module/attribute string pair passed to
   `fetch_versioned_implementation` before deleting anything in
   `backend/onyx/utils/encryption.py`, `backend/onyx/access/access.py`, or any
   file with the do-not-delete comment.
6. **A new `ee/` module must mirror its CE counterpart's module path
   exactly.** `fetch_versioned_implementation` derives `ee.<module>` from
   `module` by string prefixing; there is no separate registry to update.
7. **`global_version` is process-local, not deployment-wide.** It is set once
   at import time per process (`onyx.main`, each Celery `versioned_apps/*.py`
   entry point). Different processes in the same deployment can resolve
   differently if built from different images;
   do not assume the API server and a worker agree.
8. **EE code loaded is not the same as EE features unlocked.** Gating a new
   paid feature must go through `get_tier` (or
   equivalent tier/license checks), not through `global_version.is_ee_version()`
   alone; the latter only tells you which code is importable, not whether the
   deployment is licensed for it.

---

## 6. Relationships

**Depends on**
- [[auth-and-identity]]: `require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)`
  gates every license endpoint.
- [[multi-tenancy]]: `MULTI_TENANT` changes which gating path runs
  (control-plane vs. self-hosted license middleware) and whether the PostHog
  feature-flag provider is even attempted.

**Depended on by**
- [[access-control]] and [[permission-sync]]: `backend/onyx/access/access.py`
  and the external-permissions censoring path both dispatch through
  `fetch_versioned_implementation` / `fetch_ee_implementation_or_noop` for
  their EE-only pieces.
- [[cc-pairs-and-credentials]]: credential encryption at rest
  (`encrypt_string_to_bytes` / `decrypt_bytes_to_string`) is a versioned
  symbol; see §9.
- [[background-jobs]]: every Celery app variant under
  `backend/onyx/background/celery/versioned_apps/` calls
  `set_is_ee_if_available()` before building its app.
- [[observability]]: license and tier decisions are logged via
  `global_version`/`get_tier` state, useful when diagnosing which code path a
  request actually took.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new versioned symbol (new `fetch_versioned_implementation` call) | both a CE and an `ee.` implementation exist at the mirrored path with an identical signature; add the `# IMPORTANT DO NOT DELETE` comment on the CE side; decide `fetch_versioned_implementation` vs. `_with_fallback` vs. `_or_noop` deliberately, per §4.2 |
| changes how EE code is detected (`is_ee_available`, `set_is_ee_if_available`) | every place that calls `is_ee_available` directly rather than through `global_version` (`backend/onyx/background/celery/tasks/beat_schedule.py`); the unit-suite `_reset_leaked_ee_state` fixture assumption in `backend/tests/unit/conftest.py`; `backend/tests/unit/onyx/utils/test_ee_detection.py` |
| changes the Dockerfile's `ee` copy or the `ee` requirements split | `backend/Dockerfile:COPY ./ee`, `backend/requirements/ee.txt`; a build that stops shipping `ee` flips every standard deployment's default resolution from EE to CE, which is the whole safety story in §5 point 2 |
| adds a feature flag | whether it is a per-user boolean (`feature_enabled_for_user_tenant`) or a tenant-wide variant (`feature_variant_for_tenant`); what an unresolvable flag must do, since the first returns `False` when it cannot resolve; whether `MULTI_TENANT` gating on the PostHog provider is the intended scope, since self-hosted always gets `NoOpFeatureFlagProvider` unless `DEV_MODE` |
| changes licensing (claim/upload/refresh/delete/downgrade, or `get_tier`) | `MULTI_TENANT` rejection branches in `ee/onyx/server/license/api.py`; `apply_license_status_to_settings` in `ee/onyx/server/settings/api.py`; seat-limit and `GATED_ACCESS` behaviour in `license_enforcement.py` |
| changes `gated_app`/`GatedActionPolicy` policy resolution | every consumer: `server/features/mcp/api.py`, `server/features/build/external_apps/api.py`, `sandbox_proxy/addons/gate.py`, `external_apps/matching/engine.py`; this is unrelated to CE/EE dispatch and must not be conflated with it |

---

## 8. How to verify a change

### Telling which implementation is live at runtime

- Log line: `set_is_ee_if_available()` calls `logger.notice(...)`
  with "Enterprise Edition code is loaded" when it sets the flag; grep
  `backend/log/api_server_debug.log`
  for that string, or for "Running Enterprise Edition" logged in
  `backend/onyx/main.py`'s `__main__` block.
- Programmatically: `from onyx.utils.variable_functionality import global_version; global_version.is_ee_version()`.
- Per-symbol: `fetch_versioned_implementation` logs
  `"Fetching versioned implementation for %s.%s"` at debug level for every
  call, naming the exact module resolved.

### Tests

```bash
cd backend && uv run pytest tests/unit -k "variable_functionality or license or tier or feature_flag"
cd backend && uv run pytest tests/unit/onyx/utils/test_ee_detection.py
cd backend && uv run pytest tests/unit/ee/onyx/server/middleware/test_license_enforcement.py
cd backend && uv run pytest tests/unit/ee/onyx/utils/test_tier.py
cd backend && uv run pytest tests/integration -k license
```

`backend/tests/unit/conftest.py:_reset_leaked_ee_state` is an autouse fixture
that undoes EE state leaked by import side effects: because
`set_is_ee_if_available()` runs at module level in `onyx.main` and
every `versioned_apps/*.py`, and the repository ships the EE code, any
unit test whose import chain reaches one of those modules silently flips
`global_version` to EE for every later test in the same worker. The fixture
calls `global_version.unset_ee()` and `fetch_versioned_implementation.cache_clear()`
before each test unless the test explicitly opts into EE via the shared
`enable_ee` fixture (`backend/tests/conftest.py`). `backend/tests/integration/conftest.py`
takes the opposite stance for integration tests: it imports `onyx.main` first,
deliberately, before any dispatcher call, to avoid a re-entrant
`fetch_versioned_implementation` recursion while `ee.onyx.main` is mid-import
(see the comment above the import in that file). `backend/tests/daily/conftest.py`
calls `global_version.unset_ee()` and `fetch_versioned_implementation.cache_clear()`
at module level, after it imports `onyx.main`, for a suite that wants CE-only
resolution by construction.

To exercise the CE path in a test, call `global_version.unset_ee()` and
`fetch_versioned_implementation.cache_clear()`, matching what
`_reset_leaked_ee_state` does. No environment variable gives CE resolution.

### Manual reproduction

1. `grep -n "Enterprise Edition" backend/log/api_server_debug.log`
   at server startup to see whether `set_is_ee_if_available` loaded the EE
   code.
2. Confirm `GET http://localhost:3000/api/license` and
   `GET http://localhost:3000/api/admin/settings` behave as expected for the
   current tier.
3. To unlock paid features locally, seed a license. Set `ONYX_DEV_LICENSE` to a
   signed license and run `python -m scripts.seed_dev_license` from `backend/`
   (`backend/scripts/seed_dev_license.py:main`). The script verifies the
   signature, then stores the license. With an empty `ONYX_DEV_LICENSE` it does
   nothing.
4. A standard checkout cannot run the CE-only path, because it ships
   `backend/ee/onyx`. Use the test approach above to confirm that a versioned
   symbol resolves to the non-`ee.` module (see §9 for what changes).

---

## 9. Footguns

- **Reading `backend/onyx/utils/encryption.py:_encrypt_string` alone gives
  the wrong answer about whether Onyx encrypts credentials.** That function
  returns `input_str.encode()` unchanged; it is a real no-op. But because
  `backend/Dockerfile` always ships `./ee` and `set_is_ee_if_available` loads
  it, the implementation that actually runs in a standard
  deployment is `backend/ee/onyx/utils/encryption.py:_encrypt_string`, which
  performs real AES-CBC encryption keyed by `ENCRYPTION_KEY_SECRET`. This
  project has already made this exact mistake once: concluding "Onyx never
  encrypts credentials" from the CE file alone. It normally does. Always
  check which implementation `global_version.is_ee_version()` resolves to for
  the deployment in question before drawing a conclusion from a CE-only file.
- **No configuration selects the edition.** `is_ee_available` reads the build,
  not the environment. An operator cannot switch a standard image to CE code.
  A self-hosted operator cannot turn license enforcement off.
- **Symbols reached only via `fetch_versioned_implementation` look unused to
  static analysis.** `importlib.import_module` + `getattr` with string
  arguments is invisible to "find references" tooling and to naive
  dead-code-cleanup passes; the `# IMPORTANT DO NOT DELETE` comments exist
  specifically to stop that.
- **`fetch_ee_implementation_or_noop`'s no-op captures its return value at
  dispatch time, not at call time.** In the `post_query_censoring` call site,
  `noop_return_value` is the already-retrieved, already-ACL-filtered chunk
  list; the returned closure ignores whatever `chunks=`/`user=` it is later
  called with and simply hands back that captured list. This is intentional
  (it's an identity fallback) but easy to misread as "the function actually
  runs with these arguments."
- **EE code loaded does not mean EE features are unlocked.** `global_version.is_ee_version()`
  being `True` only means `ee.<module>` resolved. Whether a paid feature
  actually responds is a separate, license/tier-driven decision
  (`get_tier`, `apply_license_status_to_settings`). Do not gate a new paid feature on
  `global_version.is_ee_version()` alone.
