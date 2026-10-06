# Billing

> The commercial layer on top of [[editions-and-gating]]'s license/tier dispatch: Stripe
> checkout and portal, license claim and seat counting for self-hosted, and the
> control-plane billing proxy for cloud. It decides what a customer pays for and
> answers "what tier is this tenant on," not whether EE code is loaded.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** platform
**Edition:** EE only. Self-hosted billing and cloud billing share one API surface
but route to different backends.
**Owns:**
`backend/ee/onyx/server/billing/` (`api.py`, `service.py`, `billing_cache.py`,
`models.py`), `backend/ee/onyx/server/license/` (`api.py`, `models.py`),
`backend/ee/onyx/utils/tier.py`, `backend/onyx/server/settings/tier_order.py`,
`backend/onyx/db/models.py:License`, `web/src/app/admin/billing/` (`page.tsx`,
`PlansView.tsx`, `CheckoutView.tsx`, `BillingDetailsView.tsx`,
`LicenseActivationCard.tsx`), `web/src/lib/billing/` (`svc.ts`, `types.ts`)

---

## 1. What the user experiences

An admin opens **Plans & Billing** (`ADMIN_ROUTES.BILLING`,
`web/src/lib/admin-routes.ts`) and sees one of two views. With no active
subscription and no license, they see a plans picker (Business or Enterprise,
`web/src/app/admin/billing/PlansView.tsx`) and can start Stripe checkout.
With an active subscription or license, they see billing details: renewal
date, seat usage, and a "manage subscription" link into the Stripe customer
portal.

Self-hosted admins additionally see a license activation card
(`web/src/app/admin/billing/LicenseActivationCard.tsx`) where they can paste a
license key by hand, for air-gapped deployments that cannot reach Stripe or
the cloud data plane at all.

Ending a free trial early, updating seat count, and reconnecting after a
Stripe outage (a "Connect to Stripe" retry button) are all done from this same
page. On self-hosted, if the org exceeds its seat count, requests outside the
license allowlist return a 402 until seats are reduced or the plan is
upgraded (see §5). Billing, auth, and user-management routes stay open.

---

## 2. Surfaces

### HTTP endpoints, unified billing (router prefix `/admin/billing`,
`backend/ee/onyx/server/billing/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/admin/billing/create-checkout-session` | `create_checkout_session` | Rejects if requested seats < current used seats. |
| POST | `/admin/billing/create-customer-portal-session` | `create_customer_portal_session` | Self-hosted requires an existing license. |
| GET | `/admin/billing/billing-information` | `get_billing_information` | Cached (§5). Self-hosted with no license returns `SubscriptionStatusResponse(subscribed=False)` without a network call. |
| POST | `/admin/billing/seats/update` | `update_seats` | Rejects if new count < used seats. Busts the billing-info cache and the claim cooldown. |
| POST | `/admin/billing/end-trial` | `end_trial` | Cloud-only. 402 if no payment method on file. |
| GET | `/admin/billing/stripe-publishable-key` | `get_stripe_publishable_key` | Unauthenticated (publishable keys are not secret). In-memory cached. |
| POST | `/admin/billing/reset-connection` | `reset_stripe_connection` | Closes the self-hosted circuit breaker (§5). |

All authenticated handlers gate on
`require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)`.

### License endpoints (router prefix `/license`, self-hosted only,
`backend/ee/onyx/server/license/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/license` | `get_license_status` | |
| GET | `/license/seats` | `get_seat_usage` | |
| POST | `/license/claim` | `claim_license` | With `session_id`: exchanges a completed Stripe checkout for a license via the cloud data plane proxy. Without: reclaims using the stored license as auth. Rejects on `MULTI_TENANT`. |
| POST | `/license/upload` | `upload_license` | Manual signed license file, for air-gapped self-hosted. Rejects on `MULTI_TENANT`. |
| POST | `/license/refresh` | `refresh_license_cache_endpoint` | Re-reads the DB, not the control plane. |
| DELETE | `/license` | `delete_license` | Rejects on `MULTI_TENANT`. |
| POST | `/license/downgrade` | `downgrade_to_community` | Drops the deployment to the Community tier (§4.5). Returns `CommunityDowngradeResponse` (`connectors_made_public`, `user_groups_removed`). Rejects on `MULTI_TENANT`. |

All of these gate on `FULL_ADMIN_PANEL_ACCESS` too, and are sync `def` (not
`async def`) because the work is blocking: `requests` calls, sync SQLAlchemy,
RSA signature verification (module docstring,
`backend/ee/onyx/server/license/api.py`).

### Frontend routes to backend

`web/src/lib/billing/svc.ts:getBillingBaseUrl` picks `/api/tenants` (legacy,
cloud) or `/api/admin/billing` (self-hosted and the unified path) based on
`NEXT_PUBLIC_CLOUD_ENABLED`. License actions
(`web/src/lib/billing/svc.ts:selfHostedPost`) always hit `/api/license/*` and
throw if `NEXT_PUBLIC_CLOUD_ENABLED` is true.

### Environment variables

| Variable | Read in | Effect |
|---|---|---|
| `MULTI_TENANT` | `shared_configs/configs.py` | Selects the cloud vs. self-hosted branch throughout this component. |
| `CLOUD_DATA_PLANE_URL` | `ee/onyx/configs/app_configs.py` | Default `https://cloud.onyx.app/api`. Self-hosted proxy target for `/proxy/claim-license`, `/proxy/create-checkout-session`, etc. |
| `CONTROL_PLANE_API_BASE_URL` | `onyx/configs/app_configs.py` | Default `http://localhost:8082`. Cloud's direct billing target. |
| `BILLING_CACHE_TTL_SECONDS` | `onyx/configs/app_configs.py`, read by `billing_cache.py` | Default 3600. TTL for the per-tenant billing-info cache (§5). |
| `STRIPE_PUBLISHABLE_KEY` (config name `STRIPE_PUBLISHABLE_KEY_OVERRIDE`), `STRIPE_PUBLISHABLE_KEY_URL` | `onyx/configs/app_configs.py` | The env override takes priority over the S3-hosted key. |

---

## 3. Data model

- `backend/onyx/db/models.py:License`: self-hosted only, singleton table
  (`Index("idx_license_singleton", text("(true)"), unique=True)`). Stores the
  raw signed license blob (`license_data: str`) plus timestamps. There is no
  parsed/structured license table; the payload is decoded and verified on
  read (`ee/onyx/utils/license.py`), and its parsed form
  (`ee/onyx/server/license/models.py:LicenseMetadata`) is cached in Redis, not
  Postgres.
- No dedicated seat table. Seats are counted live:
  `ee/onyx/db/license.py:get_used_seats` counts active `UserTenantMapping`
  rows on cloud (`MULTI_TENANT`), keeping only rows whose `User` is active and
  excluding the anonymous user
  (`ee/onyx/db/user_tenant_mapping.py:get_tenant_count`). On self-hosted it
  counts active `User` rows excluding `AccountType.EXT_PERM_USER`,
  `AccountType.SERVICE_ACCOUNT`, and the anonymous user.
  `ee/onyx/db/license.py:user_counts_toward_seats`
  is the per-user predicate kept manually in sync with that query's filter.
- No local subscription/plan table on either deployment type. Cloud billing
  state (Stripe subscription id, status, period dates, seats) lives entirely
  on the control plane and is fetched, never stored locally beyond the Redis
  caches in §5. `backend/onyx/db/tenant_shard.py` is unrelated to seats or
  billing; it is not part of this component's data model.
- Redis keys: `billing:info:{tenant_id}` (`billing_cache.py:BILLING_CACHE_KEY`),
  the admin-page cache `billing-information:v1`
  (`ee/onyx/server/billing/api.py:BILLING_INFO_CACHE_KEY`), the self-hosted
  circuit breaker `billing_circuit_open`
  (`ee/onyx/server/billing/api.py:BILLING_CIRCUIT_BREAKER_KEY`), and the
  license metadata cache read by `ee/onyx/db/license.py:get_cached_license_metadata`.

---

## 4. How it works

### 4.1 Tier resolution (`ee/onyx/utils/tier.py:get_tier`)

```
get_tier(tenant_id=None)
  not MULTI_TENANT -> _self_hosted_tier()
      get_cached_license_metadata() -> Redis hit -> tier_from_license_metadata()
      Redis miss/error -> refresh_license_cache() from DB
      DB error (missing table, etc.) -> Tier.COMMUNITY
      no license in Redis or the DB -> Tier.COMMUNITY
  MULTI_TENANT -> tenant_id == POSTGRES_DEFAULT_SCHEMA -> Tier.BUSINESS (public schema floor)
      get_cached_tier(tid) hit -> _cloud_tier(customer_tier)
      recent miss marker set -> Tier.BUSINESS
      else -> lazy refresh from control plane -> cache it -> _cloud_tier(...)
      Redis read failure, or control-plane lookup failure -> Tier.BUSINESS
      (a Redis write failure after a good refresh still returns the fresh tier)
```

`tier_from_license_metadata` (`ee/onyx/utils/tier.py:tier_from_license_metadata`)
maps `LicenseMetadata` to `Tier`: `ApplicationStatus.GATED_ACCESS` forces
`Tier.COMMUNITY`; a missing or unrecognized `customer_tier` (legacy licenses
predate the field) defaults to `Tier.ENTERPRISE` for backward compatibility.
`_CUSTOMER_TIER_TO_TIER` maps the two paid wire values
(`ee/onyx/server/license/models.py:CustomerTier.BUSINESS`,
`CustomerTier.ENTERPRISE`) to `onyx/server/settings/models.py:Tier`. There is
no `CustomerTier.COMMUNITY`: Community is the absence of a paid tier, never a
value the control plane sends.

`onyx/server/settings/tier_order.py:tier_at_least` gives every caller a total
order (`COMMUNITY < BUSINESS < ENTERPRISE`) without depending on EE code, so
CE call sites can gate on tier without importing `ee`.

### 4.2 License claim (self-hosted)

```
POST /license/claim {session_id?}
  session_id given: POST {CLOUD_DATA_PLANE_URL}/proxy/claim-license {session_id}
    -> verify_and_store_license(response, keep_stored_tenant=True)
  session_id absent: reclaim_license_from_control_plane(db_session)
       (re-authenticates using the currently stored license blob)
  -> invalidate_billing_info_cache()   # a Stripe-side change makes the plan snapshot stale
```
(`ee/onyx/server/license/api.py:claim_license`)

The frontend calls this after Stripe checkout redirects back
(`web/src/app/admin/billing/page.tsx` retries claim up to 3 times with 2s
backoff, since the webhook that issues the license can race the redirect),
and again on `/seats/update` (the control plane regenerates the license
after a seat change; the frontend polls `/license/claim` after a short
delay rather than the seat-update endpoint returning the new license
inline, per the comment in
`ee/onyx/server/billing/api.py:update_seats`).

### 4.3 Checkout and portal (`ee/onyx/server/billing/service.py`)

The unified `/admin/billing` handlers, for both self-hosted and cloud, funnel through
`_make_billing_request` (`service.py:_make_billing_request`), which picks a
base URL and auth scheme by deployment type:

- Self-hosted: `{CLOUD_DATA_PLANE_URL}/proxy/*`, `Authorization: Bearer
  <license blob>` (`service.py:_get_proxy_headers`).
- Cloud: `{CONTROL_PLANE_API_BASE_URL}` directly, `Authorization: Bearer
  <data-plane JWT>` (`service.py:_get_direct_headers`,
  `generate_data_plane_token`).

The external payment provider is Stripe throughout; this codebase never
calls Stripe's API directly, only the control plane, which owns the Stripe
integration. `create_checkout_session` returns a `stripe_checkout_url`
(`ee/onyx/server/billing/models.py:CreateCheckoutSessionResponse`);
`create_customer_portal_session` returns a `stripe_customer_portal_url`, with
an optional `flow_type=payment_method_update` to deep-link straight to the
add-card screen (`ee/onyx/server/billing/models.py:StripePortalFlowType`).

### 4.4 Seat validation

Both `/admin/billing/create-checkout-session` and `/admin/billing/seats/update`
compare the requested seat count against `get_used_seats()` before calling
the service layer, and reject with `OnyxErrorCode.VALIDATION_ERROR` if the
request would under-provision seats already in use
(`ee/onyx/server/billing/api.py:create_checkout_session`,
`:update_seats`). This is a client-request-time check; it does not by itself
prevent seats going over the limit through other means (a license swap, a
control-plane-side downgrade) - that is enforced separately by
`license_enforcement.py` at request time (§5).

### 4.5 Community downgrade (self-hosted)

```
POST /license/downgrade                       ee/onyx/server/license/api.py:downgrade_to_community
  MULTI_TENANT -> OnyxError(VALIDATION_ERROR)
  make_all_cc_pairs_public__no_commit         ee/onyx/db/community_downgrade.py
  remove_custom_user_groups__no_commit        ee/onyx/db/community_downgrade.py
  disable_paid_features__no_commit            ee/onyx/db/community_downgrade.py
  db_session.commit()                         one commit for the three steps
  reset_settings()                            ee/onyx/server/enterprise_settings/store.py
  clear_chat_retention()                      onyx/server/settings/store.py
  delete_license(db_session)                  ee/onyx/db/license.py
  -> CommunityDowngradeResponse(connectors_made_public, user_groups_removed)
```

The route is under `/license`, which is in `LICENSE_ENFORCEMENT_ALLOWED_PREFIXES`
(`ee/onyx/configs/license_enforcement_config.py`). An admin can call it while an
expired license gates the other routes.

Two entry points open `web/src/sections/modals/DowngradeToCommunityModal.tsx`,
a consent screen that lists what becomes public and what is removed. Confirming
calls `web/src/lib/billing/svc.ts:downgradeToCommunity` and reloads the page.
- `web/src/app/admin/billing/DowngradeToCommunityLink.tsx`, in the billing page
  footer, renders only when self-hosted and `application_status` is
  `gated_access`.
- `web/src/components/errorPages/AccessRestrictedPage.tsx` shows a button to a
  user with `FULL_ADMIN_PANEL_ACCESS` in its self-hosted branch.

- `make_all_cc_pairs_public__no_commit` sets every cc-pair that is not `PUBLIC`
  to `PUBLIC`. It clears `auto_sync_options`, `last_time_perm_sync` and
  `last_time_external_group_sync`, deletes the data-access group rows of those
  pairs, and marks their indexed documents for index sync
  (`db/document.py:mark_cc_pair_documents_for_sync__no_commit`). For all pairs,
  it deletes every `User__ExternalUserGroupId` and `PublicExternalUserGroup` row
  and clears the synced permission columns on `Document` and `HierarchyNode`.
  The index keeps the old chunk ACLs until the metadata sync rewrites the
  marked documents. See [[cc-pairs-and-credentials]] §5 and [[permission-sync]] §5.
- `remove_custom_user_groups__no_commit` deletes every non-default user group.
  First it makes the resources shared with those groups public, and it keeps
  the members in the default groups. See [[access-control]] §3.
- `disable_paid_features__no_commit` deletes every token rate limit,
  soft-deletes every hook (`deleted=True`, `is_active=False`), deactivates
  every standard answer and SCIM token, and removes every API key with its
  service-account user, except the Discord bot's service key, which has no
  owner (`db/api_key.py:remove_all_api_keys__no_commit`).
- `reset_settings` stores a default `EnterpriseSettings`, deletes the custom
  analytics script, and deletes the logo and logotype files.
  `clear_chat_retention` sets `maximum_chat_retention_days` to `None` under
  `settings_write_lock`. A chat deletion chain that started under the old
  limit ends at its next batch ([[chat-persistence]]).

---

## 5. Contracts and invariants

1. **A billing-info cache read failure falls through to a live fetch, not to
   a default entitlement.** `billing_cache.py:cached_fetch_billing_information`
   catches `RedisError` on read and write and simply calls
   `fetch_billing_information` directly; a cache outage costs latency, not
   correctness, because the fallback is always the authoritative source
   (control plane), never a guessed tier.
2. **Tier resolution fails toward the lower tier, never the higher one.**
   Self-hosted: a DB read failure (missing table, `SQLAlchemyError`) returns
   `Tier.COMMUNITY` (`ee/onyx/utils/tier.py:_self_hosted_tier`). Cloud: a
   Redis read failure or a control-plane lookup failure returns `Tier.BUSINESS`
   (`ee/onyx/utils/tier.py:get_tier`), which is the cloud floor tier (cloud
   has no `Tier.COMMUNITY`; the public schema itself resolves to `BUSINESS`
   unconditionally). Neither path can fail toward `ENTERPRISE`.
3. **`apply_license_status_to_settings` fails closed on cache failure, explicitly.**
   `ee/onyx/server/settings/api.py:apply_license_status_to_settings` catches
   `CACHE_TRANSIENT_ERRORS`, sets `ee_features_enabled` to `False` and `tier`
   to `Tier.COMMUNITY`, with the comment "Fail closed - disable EE features if
   we can't verify license." This is a different failure
   mode from point 4 below; do not conflate the two.
4. **The self-hosted license-enforcement middleware fails *open* on cache
   transient errors, deliberately.** `ee/onyx/server/middleware/license_enforcement.py`
   catches `CACHE_TRANSIENT_ERRORS` around its metadata read and sets
   `is_gated = False` with the comment "Fail open - don't block users due to
   cache connectivity issues." This governs whether a request is *blocked*
   (availability), not which *tier* a feature check resolves to (point 2);
   the two mechanisms can legitimately disagree in the same request path
   without being a bug.
5. **A seat-limit breach blocks every non-allowlisted self-hosted request
   with 402, not just the billing page.** `license_enforcement.py` compares
   `metadata.used_seats > metadata.seats` once a license is active and
   returns `{"error": "seat_limit_exceeded", ...}`. Paths in
   `LICENSE_ENFORCEMENT_ALLOWED_PREFIXES` skip the check (auth, license,
   billing, `/manage/users`, and similar), so admins can fix the breach. The
   middleware does not run on cloud (`MULTI_TENANT`); cloud gating is
   separate.
6. **`/license/claim`, `/license/upload`, `/license/refresh`, `DELETE
   /license`, `/license/downgrade` all reject outright on `MULTI_TENANT`.** Cloud licensing has no
   local license row at all; these handlers assume self-hosted and 400 rather
   than silently no-op on cloud.
7. **Seat-count writes cannot under-provision current usage.** Both checkout
   and seat-update reject a target seat count below `get_used_seats()`
   server-side (§4.4); the frontend's own validation is not trusted as the
   only guard.
8. **EE code loading, license validity, and tier are three separate
   questions.** Per [[editions-and-gating]]: `global_version.is_ee_version()`
   only says `ee.<module>` imported. `ee_features_enabled` on `GET /settings`
   (`ee/onyx/server/settings/api.py:apply_license_status_to_settings`) says
   whether the deployment may use paid features at all (a boolean gate).
   `get_tier()` says *which* tier, for tier-specific behavior
   (`tier_at_least`). A change must not conflate these, e.g. gating a
   Business-only feature on `ee_features_enabled` alone would let an
   Enterprise-license-holding Community-intent deployment through
   incorrectly if such a state existed; always use `tier_at_least(get_tier(),
   Tier.X)` for tier-specific gates.
9. **The Community downgrade deletes the license last.**
   `ee/onyx/server/license/api.py:downgrade_to_community` commits the database
   changes and resets the settings before it calls `delete_license`. A failure
   before that call leaves a licensed deployment, and a second call completes
   the downgrade. A change that deletes the license earlier breaks this.

---

## 6. Relationships

**Depends on**
- [[editions-and-gating]]: owns the EE-code-loading dispatch this component's
  tier resolution builds on; `apply_license_status_to_settings`
  and `get_tier` are the two functions that component's §4.4 names as the
  license half of the picture.
- [[multi-tenancy]]: `MULTI_TENANT` is the fork point for nearly every
  function in `service.py`, `tier.py`, and `billing_cache.py`.
- [[auth-and-identity]]: every authenticated endpoint here gates on
  `Permission.FULL_ADMIN_PANEL_ACCESS`; seat counting on self-hosted reads
  `User.account_type` and `User.is_active` from that same user table.
- [[rate-and-usage-limits]]: `billing_cache.py`'s docstring explains its
  reason for existing is to absorb the read load `_check_chunk_usage_limit`
  would otherwise put on the control plane; `cached_is_tenant_on_trial` feeds
  that usage-limit path directly.

**Depended on by**
- [[rate-and-usage-limits]]: trial-status and tier are both inputs to usage
  limit enforcement.
- Nothing in the chat/search/ingestion path calls into billing directly;
  its effect on the rest of the product is entirely mediated through
  `get_tier()` / `tier_at_least()` calls made
  elsewhere, per [[editions-and-gating]].

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new `CustomerTier` value or changes `_CUSTOMER_TIER_TO_TIER` | `tier_from_license_metadata` and `_cloud_tier`'s unknown-tier fallback (`Tier.BUSINESS`); every `tier_at_least` call site that assumes only three `Tier` values |
| changes `BILLING_CACHE_TTL_SECONDS` or `BILLING_INFO_CACHE_TTL_SECONDS` | how stale an entitlement can appear post-purchase; whether `invalidate_billing_info_cache` is called from every mutation path (`create_checkout_session`, `update_seats`, `end_trial`, `/license/claim`; `/license/upload`, `/license/refresh`, `DELETE /license`, and `/license/downgrade` do not call it today) |
| changes seat-counting logic (`get_used_seats`, `user_counts_toward_seats`) | keep the two in sync (the module comment says so explicitly); `license_enforcement.py`'s 402 threshold uses the cached `used_seats`, which is a separate write path from the live count |
| changes the license-enforcement middleware's fail-open/fail-closed behavior | §5 points 3 and 4; do not accidentally make it fail closed on transient Redis errors, which would lock out every self-hosted customer during a Redis blip |
| adds a new billing endpoint | whether it needs the self-hosted circuit breaker treatment (`_is_billing_circuit_open`/`_open_billing_circuit`), and whether it must call `invalidate_billing_info_cache()` after a state-changing operation |
| changes `EnterpriseSettings`/theming tier gates | this is [[whitelabelling-and-theme]]'s concern, not this one; do not duplicate its Enterprise-tier field gating here |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/ee/onyx/server/billing/test_billing_api.py
cd backend && uv run pytest tests/unit/ee/onyx/server/billing/test_billing_service.py
cd backend && uv run pytest tests/unit/ee/onyx/server/billing/test_billing_cache.py
cd backend && uv run pytest tests/unit/ee/onyx/server/billing/test_proxy.py
cd backend && uv run pytest tests/unit/ee/onyx/server/license/test_api.py
cd backend && uv run pytest tests/unit/ee/onyx/server/tenants/test_billing_api.py
cd backend && uv run pytest tests/unit/ee/onyx/server/tenants/test_billing_seat_enforcement.py
cd backend && uv run pytest tests/unit/ee/onyx/server/middleware/test_license_enforcement.py
cd backend && uv run pytest tests/unit/ee/onyx/server/settings/test_license_enforcement_settings.py
cd backend && uv run pytest tests/unit/ee/onyx/utils/test_tier.py
cd backend && uv run pytest tests/unit/ee/onyx/db/test_license.py
cd backend && uv run pytest tests/external_dependency_unit/ee/onyx/db/test_community_downgrade.py
cd backend && uv run pytest tests/external_dependency_unit/ee/onyx/db/test_community_downgrade_groups.py
cd backend && uv run pytest tests/external_dependency_unit/ee/onyx/db/test_community_downgrade_paid_features.py
```

Frontend:

```bash
cd web && bun run test -- src/lib/billing/svc.test.ts
cd web && bun run test -- src/app/admin/billing/page.test.tsx
```

No playwright e2e target exists for billing; theming has
one (see [[whitelabelling-and-theme]] §8) but the billing/checkout flow does
not.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Self-hosted, no license: open `http://localhost:3000/admin/billing`,
   confirm the plans view renders and checkout redirects to a Stripe URL.
3. Self-hosted with a manually issued license: use the license activation
   card to paste a key, confirm `GET /api/license` reflects it and the page
   switches to the details view.
4. To exercise seat enforcement, set a tenant's used seats above its licensed
   seat count in the DB and confirm subsequent requests return 402 with
   `error: "seat_limit_exceeded"`.
5. Grep `backend/log/api_server_debug.log` for `[license_enforcement]` to see
   which branch (`GATED_ACCESS`, seat limit, no license) a given request took.

---

## 9. Footguns

- **A directory under `web/src/app/ee/admin/` is reachable only if its path is in
  `web/src/proxy.ts:EE_ROUTES`.** The billing route `/admin/billing`
  (`ADMIN_ROUTES.BILLING`, `web/src/lib/admin-routes.ts`) is not in `EE_ROUTES`.
  The page lives in `web/src/app/admin/billing/`: `page.tsx`, `PlansView.tsx`,
  `CheckoutView.tsx`, `BillingDetailsView.tsx` and `LicenseActivationCard.tsx`.
  Theme is the opposite case: `/admin/theme` is in `EE_ROUTES`, so the
  `/ee/admin/theme` tree is the live page (see [[whitelabelling-and-theme]] §9).
- **`GatedContentWrapper` exempts `/admin/billing` and `/admin/users` from
  the gated-access lockout by pathname string match**
  (`web/src/components/GatedContentWrapper.tsx:ALLOWED_GATED_PATHS`), so a
  fully expired self-hosted instance can still reach billing to fix itself.
  Renaming this route without updating that list would lock out every
  expired customer from the one page that lets them recover.
- **A legacy license (issued before `customer_tier` existed) resolves to
  `Tier.ENTERPRISE`, not `Tier.BUSINESS`.** `tier_from_license_metadata`
  treats "unknown/missing tier" as ENTERPRISE for backward compatibility;
  reading this as "unknown defaults to the safe/low tier" is backwards for
  self-hosted (though correct for cloud's separate `_cloud_tier` fallback,
  which defaults unknown to BUSINESS). The two "unknown" defaults are
  different tiers on purpose; do not assume they match.
- **`backend/onyx/db/tenant_shard.py`** has no billing-, seat-, or
  tier-related content. There is no local subscription table at all; cloud
  billing state lives only on the control plane.
- **Checking used seats twice, cheaply and expensively.** `get_used_seats`
  hits the DB live on every checkout/seat-update call; `license_enforcement.py`'s
  402 check reads a cached `used_seats` from `LicenseMetadata` instead. These
  can disagree briefly after a user is added or removed until the cache is
  invalidated; do not assume they are always the same number in a test.

---

Cross-links: [[editions-and-gating]], [[multi-tenancy]], [[auth-and-identity]],
[[rate-and-usage-limits]], [[observability]], [[whitelabelling-and-theme]]
