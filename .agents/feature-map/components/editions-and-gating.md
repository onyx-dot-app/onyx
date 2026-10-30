# Editions and Gating

> How a call reaches Community (CE) or Enterprise (EE) code, and how a paid
> feature is locked below its tier. Every standard image loads the EE code, so the
> license decides what is unlocked, not the build.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE dispatcher, tier order and feature-flag interface. EE
implementations, the tier gate middleware and the PostHog flag provider.

---

## Callers

**Interface.**
- Dispatch: `backend/onyx/utils/variable_functionality.py`, with
  `fetch_versioned_implementation`, `fetch_versioned_implementation_with_fallback`,
  `fetch_ee_implementation_or_noop`, and `set_is_ee_if_available` for process
  entry points.
- Tier checks: `backend/onyx/server/settings/tier_order.py:tier_at_least` and
  `get_current_tier`, and the route map
  `backend/ee/onyx/configs/license_enforcement_config.py:PATH_PREFIX_MIN_TIER`. A
  rejection is HTTP 402 `FEATURE_NOT_AVAILABLE` with `required_tier`.
- Web: `tier` and `ee_features_enabled` from `GET /settings`, read through
  `web/src/lib/tiers/hooks.ts:useTierAtLeast`.
- Feature flags:
  `backend/onyx/feature_flags/factory.py:get_default_feature_flag_provider`.

**Who calls it.**
- Developers who add a paid feature, a CE function with an EE version, a feature
  flag or a process entry point. The recipes below cover each one.
- Components with EE pieces reach them through the dispatcher:
  [[access-control]], [[permission-sync]], [[cc-pairs-and-creds]],
  [[rate-and-usage-limits]], [[auth-and-identity]] and [[billing]]. In CE, an
  EE-only check is a no-op that returns a fixed value.
- [[craft-sessions]] reads the craft flag and compares the tier with
  `LLM_GATEWAY_MIN_TIER`.
- [[llm-gateway]] is locked by its prefix in `PATH_PREFIX_MIN_TIER`.
- The web client gates pages and options with `useTierAtLeast`, and on a 402
  shows the plan and an upgrade link to [[billing]].

**Keys a caller must keep:** [[#loaded-ee-not-unlocked]],
[[#entry-point-sets-edition]], [[#versioned-symbol-same-signature]],
[[#noop-not-only-security-control]], [[#allowlist-skips-tier-gate]],
[[#one-tier-error-shape]] and [[#flags-off-self-hosted]].

---

## Scope

This component owns:
- the CE-to-EE dispatcher and the process-wide edition flag;
- the tier order and its web mirror;
- tier gating of routes, of fields inside shared routes, and the CE helpers that
  EE implements as tier guards;
- the feature-flag interface and its providers.

Its neighbours own:
- [[billing]]: the license, `get_tier` resolution and its failure modes, seats,
  license-state blocking (`GATED_ACCESS`, seat limit), cloud subscription gating
  and the Community downgrade.
- [[access-control]]: the document ACL that the EE censoring adds to.
- [[craft-external-apps]]: `GatedApp` and the Craft action policies. The name
  says "gated", but this is not an edition or tier boundary.
- [[multi-tenancy]]: the `MULTI_TENANT` switch and the tenant contextvar that the
  tier gate reads.
- [[chat-preferences]]: the workspace `Settings` store, its write lock and its
  public read. This component owns only the tier rules for paid fields.

---

## Architecture

**Edition resolution.**

```
process entry point (onyx.main, each celery versioned_apps/*.py, alembic env,
slack listener, discord client, mcp server, sandbox proxy, some scripts)
  -> set_is_ee_if_available()          global_version.set_ee() if is_ee_available()
                                       is_ee_available: find_spec("ee.onyx") has an origin
later, at a call site
  -> fetch_versioned_implementation(module, attr)     lru_cache
       EE: import "ee." + module; on a missing ee.onyx module, fall back to CE
       CE: import module
```

`global_version` is a plain object in each process, so each process decides once.
Two processes built from different images can disagree. No env var selects the
edition: `is_ee_available` reads the build, not the environment.
The MIT-only `onyx-foss` mirror is built by `backend/scripts/make_foss_repo.sh`,
which removes `backend/ee` and leaves an empty package. It is the only build that
runs the CE implementations.

**Three dispatch helpers.** Pick one on purpose.

| Helper | When the symbol is missing | Use it for |
|---|---|---|
| `fetch_versioned_implementation` | Raises, except the EE-to-CE fallback | Symbols that exist on both sides, such as `_encrypt_string` |
| `fetch_versioned_implementation_with_fallback` | Returns the fallback on any error | Optional providers, such as the PostHog flag provider |
| `fetch_ee_implementation_or_noop` | In CE, returns a no-op without an import. In EE, raises | EE-only behaviour that CE skips, such as the tier guards and seat checks |

The CE no-op returns `noop_return_value` and ignores its arguments. When
`noop_return_value` is a coroutine function, the no-op calls it with the same
arguments and awaits it. An
EE-only module needs no CE file: `onyx.utils.tier` exists only as
`backend/ee/onyx/utils/tier.py`.

**Tier gating.** A paid feature is locked by tier at one or more of these layers:

```
whole route      tier_gate_middleware       longest prefix in PATH_PREFIX_MIN_TIER
                                            -> get_tier() -> tier_at_least -> 402 + required_tier
one field        inline tier_at_least(current tier, Tier.X)
                 settings admin_patch_settings, PAT scopes, EE admin_ee_put_settings
CE helper        fetch_ee_implementation_or_noop("onyx.utils.tier", "require_business_tier_for_...")
                 connector pairing access, security settings, SSO providers
web              useTierAtLeast / tierAtLeast on settings.tier; app/ee/layout.tsx on ee_features_enabled
```

`backend/ee/onyx/main.py:get_application` registers `tier_gate_middleware` in
both self-hosted and cloud mode. It registers it first, so it runs after the
tenant middleware has set the tenant. `GET /settings` returns `tier` and
`ee_features_enabled` from
`backend/ee/onyx/server/settings/api.py:apply_license_status_to_settings`.

**Settings writes.** `backend/onyx/server/settings/api.py:admin_patch_settings`
merges the fields the caller sent under the store's lock
([[chat-preferences#settings-write-under-lock]]). It gates paid fields inline
when their value changes: `search_ui_enabled` and
`llm_gateway_enabled` need Business, and `maximum_chat_retention_days` needs
Enterprise.

**Craft availability.**
`backend/onyx/server/features/build/utils.py:is_craft_available_for_deployment`
needs the craft flag (PostHog `onyx-craft-enabled`, or `ENABLE_CRAFT` without
PostHog) and `LLM_GATEWAY_MIN_TIER`, because every Craft turn uses the gateway.
`is_craft_locked_by_tier` sets `onyx_craft_requires_upgrade` in the settings
response, which drives the upgrade page.

**Feature flags.**
`backend/onyx/feature_flags/factory.py:get_default_feature_flag_provider`
returns `NoOpFeatureFlagProvider` unless `MULTI_TENANT` or `DEV_MODE` is set.
With either set, it tries the EE PostHog provider. That provider also falls back
to the no-op when no PostHog client is configured.
`feature_enabled_for_user_tenant` evaluates a flag for one user.
`feature_variant_for_tenant` reads one variant for the whole tenant.

---

## Contracts and traps

1. `ce-file-not-running-code` **The CE file is not the code that runs.** Every
   standard image copies `backend/ee` (`backend/Dockerfile`), so `ee.<module>`
   wins. `backend/onyx/utils/encryption.py:_encrypt_string` returns the input
   unchanged, but deployments run
   `backend/ee/onyx/utils/encryption.py:_encrypt_string`, which encrypts with
   AES. Read the `ee.` mirror before you conclude what Onyx does. Every
   encrypted column and cache entry is encrypted only when EE code is loaded and
   `ENCRYPTION_KEY_SECRET` is set. Without the key, the EE function also stores
   plain text, and a key shorter than 16 bytes raises `RuntimeError`
   (`backend/ee/onyx/utils/encryption.py:_get_trimmed_key`). The CE function only
   logs a warning when the key is set.
2. `loaded-ee-not-unlocked` **Loaded EE code is not an unlocked feature.** Gate a
   paid feature on `backend/onyx/server/settings/tier_order.py:tier_at_least`,
   never on `global_version.is_ee_version()`. The latter is true on every
   standard deployment, licensed or not. Scheduled EE tasks follow the build too:
   `backend/onyx/background/celery/tasks/beat_schedule.py` adds the permission
   sync tasks when `is_ee_available()` is true, whatever the license.
3. `entry-point-sets-edition` **Every process entry point must call
   `set_is_ee_if_available()` before its first versioned lookup.**
   (`backend/onyx/utils/variable_functionality.py:set_is_ee_if_available`) A
   process that skips it resolves every symbol to CE: secrets stay unencrypted
   and EE checks become no-ops. `fetch_versioned_implementation` caches its answer, so a lookup
   at import time, before the flag is set, keeps the CE answer for the life of
   the process. Look up versioned symbols at call time.
4. `versioned-symbol-same-signature` **A versioned symbol must keep its module
   path and signature on both sides.** The EE path is `"ee." + module`, by
   string. No type check crosses that boundary. A mismatch fails at call time in
   production.
5. `dispatch-symbols-look-unused` **Symbols reached only through dispatch look
   unused.** The lookup is `importlib` plus `getattr` on strings. Before you
   delete a function that has the `# IMPORTANT DO NOT DELETE` comment, or any
   function in a module that a dispatcher names, grep for the module and
   attribute strings.
6. `noop-not-only-security-control` **A no-op fallback must never be the only
   enforcement of a security control.** It may skip only an extra layer. For
   example, `backend/onyx/access/access.py:censor_chunks_for_user` returns the
   chunks unchanged in CE. That is safe only because the index ACL filter runs in
   every edition ([[access-control]]). The hierarchy queries are an exception on
   purpose: the CE versions in `backend/onyx/db/hierarchy.py` treat every
   non-stub node as accessible, so the MIT-only build widens hierarchy access
   where EE filters it. The code comment says that Community connectors are
   public.
7. `allowlist-skips-tier-gate` **A path in
   `LICENSE_ENFORCEMENT_ALLOWED_PREFIXES` skips the tier gate as well.**
   (`backend/ee/onyx/configs/license_enforcement_config.py:LICENSE_ENFORCEMENT_ALLOWED_PREFIXES`)
   `backend/ee/onyx/server/middleware/tier_gate.py:_is_allowed_path` passes it
   before the tier lookup. Do not put a paid route under `/settings`,
   `/manage/users`, `/me` or another allowlisted prefix.
8. `longest-prefix-match` **`PATH_PREFIX_MIN_TIER` matches the longest prefix,
   after the API prefix is stripped.**
   (`backend/ee/onyx/configs/license_enforcement_config.py:PATH_PREFIX_MIN_TIER`)
   A nested path can need a higher tier than
   its parent, as `/admin/enterprise-settings/scim` does. A plain string prefix
   also matches a sibling that shares the start, such as `/analytics-foo` under
   `/analytics`.
9. `tier-gate-fails-closed` **The tier gate fails closed.** When
   `backend/ee/onyx/utils/tier.py:get_tier` raises,
   `backend/ee/onyx/server/middleware/tier_gate.py:tier_gate_middleware` treats
   the tenant as `COMMUNITY`. `get_tier` catches most errors itself and falls back as
   [[billing#failure-directions-differ]] describes.
10. `one-tier-error-shape` **Tier rejections use one error shape.** The
    middleware and the inline field checks both raise `FEATURE_NOT_AVAILABLE`
    (402). Keep new tier checks on that code, so the client handles one shape.
11. `tier-set-mirrored` **The tier set is mirrored by hand.**
    `backend/onyx/server/settings/models.py:Tier` and
    `web/src/lib/tiers/types.ts:Tier` must match. `LLM_GATEWAY_MIN_TIER` exists in
    `backend/onyx/server/gateway/configs.py` and in `web/src/lib/tiers/utils.ts`.
    The settings write gate for `llm_gateway_enabled` writes `Tier.BUSINESS`
    itself instead of reading `LLM_GATEWAY_MIN_TIER`. It must agree with the
    gateway prefix in `PATH_PREFIX_MIN_TIER`.
12. `flags-off-self-hosted` **Feature flags are off on self-hosted unless
    `DEV_MODE` is set.**
    `backend/onyx/feature_flags/factory.py:get_default_feature_flag_provider`
    returns the PostHog provider on cloud or with `DEV_MODE`, and otherwise the
    no-op provider
    (`backend/onyx/feature_flags/interface.py:NoOpFeatureFlagProvider`), which
    answers `False` for every flag. A flagged feature that must
    work self-hosted checks for `NoOpFeatureFlagProvider` and reads an env var
    instead, as `backend/onyx/server/features/build/utils.py` does with
    `ENABLE_CRAFT`.

---

## Decisions

- **EE code ships in every image.** One image serves every customer. A license
  change takes effect at runtime, so an upgrade or a downgrade needs no new
  image and no restart. The image label in `backend/Dockerfile` states the
  license terms for the EE code. Customers who need MIT-only code use the
  `onyx-foss` mirror.
- **The tier order lives in CE.** `backend/onyx/server/settings/tier_order.py`
  lets any CE module compare tiers without an import of EE code.
  `get_current_tier` returns `COMMUNITY` when EE code is not loaded.
- **Route gating is one declarative map.** `PATH_PREFIX_MIN_TIER` holds every
  paid route prefix, so a reviewer can see the paid surface in one file. Field
  gates inside shared routes stay inline, because a prefix cannot express them.

---

## Known issues

- **The web EE layout fails open.** `web/src/app/ee/layout.tsx` renders the page
  when the settings fetch fails. The backend tier gate still refuses the data
  calls. With EE features off, it passes through in `gated_access` (the root
  layout handles that state) and otherwise renders `EEFeatureRedirect`.
- **The flag key modules are not used.** `backend/onyx/feature_flags/flags.py` is
  empty, and no module imports
  `backend/onyx/feature_flags/feature_flags_keys.py`. Each feature defines its
  flag key at its call site, for example
  `backend/onyx/server/features/build/utils.py:ONYX_CRAFT_ENABLED_FLAG`.

---

## Dependencies

- [[billing]]: `get_tier` and the license state that sets the tier.
- [[multi-tenancy]]: the tenant contextvar that `tier_gate_middleware` reads, and
  `MULTI_TENANT`, which turns on the PostHog provider.

---

## Recipes

- `add-versioned-symbol` **Add a versioned symbol.** Copy `_encrypt_string`: the CE function in
  `backend/onyx/utils/encryption.py` and the EE one in
  `backend/ee/onyx/utils/encryption.py`, with the same name and signature and the
  `# IMPORTANT DO NOT DELETE` comment on the CE side. Choose the helper from the
  table in Architecture. List the current set with
  `git grep -n "fetch_versioned_implementation\|fetch_ee_implementation_or_noop" backend/onyx`.
- `add-paid-route` **Add a paid route.** Copy the `/admin/hooks` entry in
  `backend/ee/onyx/configs/license_enforcement_config.py:PATH_PREFIX_MIN_TIER`;
  that map is the current set. Check that no allowed prefix covers it
  ([[#allowlist-skips-tier-gate]]). Lock the web entry with `useTierAtLeast`. A
  page under `web/src/app/ee/admin/` loads at its `/admin/...` path only when that
  path is in `web/src/proxy.ts:EE_ROUTES`; `web/src/app/ee/layout.tsx` then
  applies the `ee_features_enabled` redirect. A missing gate leaves the feature
  open on Community and no test fails, so add a case to
  `backend/tests/unit/ee/onyx/server/middleware/test_tier_gate.py`.
- `add-paid-field` **Add a paid field in a shared route.** Copy `search_ui_enabled` (Business)
  or `maximum_chat_retention_days` (Enterprise) in
  `backend/onyx/server/settings/api.py:admin_patch_settings`: compare the old and
  new values, and raise `FEATURE_NOT_AVAILABLE` when
  `tier_at_least(get_current_tier(), ...)` fails. Lock the admin control with
  `useTierAtLeast` at the same tier, as
  `web/src/views/admin/ChatPreferencesPage.tsx` does for both fields. Without it,
  the UI offers a value that the API refuses with 402. The API check runs only on a
  write, and a stored value keeps its effect after the license lapses. So also
  check the tier where the value is read, or clear it on downgrade, as
  `backend/onyx/server/settings/store.py:clear_chat_retention` does from
  `downgrade_to_community`.
- `add-feature-flag` **Add a feature flag.** Copy `ONYX_CRAFT_ENABLED_FLAG` and its reader in
  `backend/onyx/server/features/build/utils.py`. Call
  `get_default_feature_flag_provider()` at request time, and decide what
  self-hosted gets ([[#flags-off-self-hosted]]). List the flags with
  `git grep -n "feature_enabled_for_user_tenant\|feature_variant_for_tenant" backend`.
- `add-entry-point` **Add a process entry point.** Call `set_is_ee_if_available()` at module level
  before the first versioned lookup, as
  `backend/onyx/background/celery/versioned_apps/primary.py` does. List the entry points with `git grep -n "set_is_ee_if_available()" backend`.
- `find-loaded-edition` **Find which edition a process loaded.** Search its log for "Enterprise Edition
  code is loaded".
- `test-ce-or-ee` **Run a test as CE or EE.** Importing `onyx.main` or a `versioned_apps` module
  sets the EE flag for the whole test worker.
  `backend/tests/unit/conftest.py:_reset_leaked_ee_state` clears it before each
  unit test, and the `enable_ee` fixture in `backend/tests/conftest.py` opts in.
  To test CE elsewhere, call `global_version.unset_ee()` and
  `fetch_versioned_implementation.cache_clear()`. `backend/tests/daily/conftest.py`
  calls `global_version.unset_ee()` at module level, so daily tests run CE.
- `integration-import-order` **Keep the integration import order.** `backend/tests/integration/conftest.py`
  imports `onyx.main` before its first dispatcher call. If a fixture calls
  `fetch_versioned_implementation` first, the import of `ee.onyx.main` reaches
  `onyx.main` while `ee.onyx.main` is half loaded, and the result is an
  `AttributeError` on `get_application`.
- `unlock-paid-locally` **Unlock paid features locally.** Load a license as
  [[billing#load-license-locally]] describes.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/utils/`,
  `backend/tests/unit/ee/onyx/server/middleware/` and
  `backend/tests/unit/ee/onyx/utils/`; web tier helpers in `web/src/lib/tiers/`.
- External dependency tests: `backend/tests/external_dependency_unit/tier/` and
  `backend/tests/external_dependency_unit/feature_flags/`.
- By hand: call a paid route on a deployment with no license. It must return 402
  with `required_tier`.
