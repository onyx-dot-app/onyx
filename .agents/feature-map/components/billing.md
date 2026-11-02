# Billing

> The commercial layer: Stripe checkout and portal through the Onyx control plane,
> the signed self-hosted license, seats, the tier each deployment resolves to, and
> what happens when a subscription lapses.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** EE. Self-hosted and cloud share the admin API but reach different
backends.

---

## User experience

- **An admin with no subscription** opens Plans & Billing, picks Business or
  Enterprise, and goes to Stripe checkout. On return, the page claims the license
  and shows the plan, renewal date and seat use. A "manage subscription" link
  opens the Stripe customer portal.
- **An air-gapped admin** enters a signed license key in the activation card. The
  upload needs no network access.
- **An admin who changes the seat count** cannot set it below the seats in use. A
  self-hosted instance then fetches the new license from the control plane.
- **Before a license expires**, admins see warnings at 30, 14 and 1 days. A
  license that renews itself gives no warning before expiry, except near the end
  of a trial (`backend/ee/onyx/utils/license_expiry.py:get_expiry_warning_stage`).
  A renewed subscription replaces the license with no admin action. After expiry,
  a 14-day grace period keeps everything working.
- **When the grace period ends**, the instance is gated. Every page except billing
  and user management shows an access-restricted screen. API calls get 402
  `license_expired`. An admin can renew, or downgrade to Community. The downgrade
  lists what becomes public and what is removed before it runs.
- **When a self-hosted deployment has more active users than seats**, requests
  outside the allowlist get 402 `seat_limit_exceeded` until an admin removes
  users or buys seats. Adding a user past the limit fails.
- **On cloud**, adding a user past the seat count bills one more seat through
  Stripe. A declined card blocks the add. A trial tenant can end its trial early
  once it has a payment method. A tenant whose subscription lapsed gets 402
  `SUBSCRIPTION_INACTIVE` outside the allowed prefixes: auth, health, `/me`,
  settings and billing ([[#recovery-paths-reachable]]).
- **When a self-hosted instance cannot reach Stripe**, the page shows a "Connect
  to Stripe" retry. The page stops fetching billing information for an hour, or
  until the admin clicks the retry.

---

## Scope

This component owns:
- the billing admin API, the license API and the web billing page;
- license storage, signature checks, renewal (reclaim) and expiry warnings;
- tier resolution (`get_tier`) for self-hosted and cloud;
- seat counting and the seat checks that user writes call;
- blocking a lapsed deployment: the self-hosted license middleware and the cloud
  `gated_tenants` check;
- the cloud-side `/proxy` endpoints that self-hosted instances call, and the cloud
  seat billing;
- the Community downgrade.

Its neighbours own:
- [[editions-and-gating]]: the tier order, `tier_gate_middleware` and the
  per-route tier map. A Community deployment is locked by tier there, not by this
  component.
- [[rate-and-usage-limits]]: trial usage caps. It reads trial status from the
  billing cache here.
- [[multi-tenancy]]: tenant provisioning, the tenant id that every cloud call
  carries, and the rest of the tenant middleware.
- [[auth-and-identity]]: the user writes that call the seat checks.

---

## Architecture

**Who talks to Stripe.** The control plane owns checkout, the portal and the
webhooks. Self-hosted code never calls Stripe. Cloud code calls the Stripe SDK
only to set the seat quantity: when a user is added
(`backend/ee/onyx/server/tenants/billing.py:attempt_seat_billing_increase`), and
after an admin invites users or removes an invited user
(`backend/ee/onyx/server/tenants/billing.py:register_tenant_users`, called from
`backend/onyx/server/manage/users.py`).

```
self-hosted  /admin/billing/* and /license/claim
             -> {CLOUD_DATA_PLANE_URL}/proxy/*       Authorization: Bearer <license blob>
                                                     (a checkout claim sends no license)
                backend/ee/onyx/server/tenants/proxy.py on cloud verifies the signature
             -> control plane                        data-plane JWT
cloud        /admin/billing/* and /tenants/*
             -> control plane directly               data-plane JWT
```

`backend/ee/onyx/server/billing/service.py:_make_billing_request` picks the base
URL and headers by `MULTI_TENANT`. The web client picks `/api/tenants` on cloud
and `/api/admin/billing` on self-hosted
(`web/src/lib/billing/svc.ts:getBillingBaseUrl`).

**License lifecycle (self-hosted).** The `License` table holds one signed blob.
`backend/ee/onyx/utils/license.py:verify_and_store_license` checks the RSA
signature before it stores, and it discards a blob issued before the one already
stored. Three paths bring a license in:
- `claim_license` with a Stripe `session_id`, after checkout. The page retries,
  because the webhook that issues the license can race the redirect.
- `claim_license` with no `session_id`, which reclaims with the stored blob as
  auth. It runs after a seat or plan change.
- `upload_license`, for air-gapped instances.

Within 7 days of expiry, the license middleware schedules a debounced reclaim on
the requests it checks
(`backend/ee/onyx/utils/license.py:maybe_schedule_license_reclaim`). Where the
cache backend is not Redis, the periodic poller runs the reclaim task instead. A
renewal therefore lands with no admin action. `get_license_status` derives the
status from `expires_at` and the grace end. `build_license_metadata` gives the
cache entry a TTL that ends at the next status boundary.

**Tier resolution.** `backend/ee/onyx/utils/tier.py:get_tier` returns:
- self-hosted: the license `customer_tier`. No license, or `GATED_ACCESS`, is
  `COMMUNITY`.
- cloud: the tier cached in Redis, or a lazy fetch from the control plane. The
  public schema is `BUSINESS`.

**Seats.** `backend/ee/onyx/db/license.py:get_used_seats` counts live.
Self-hosted counts active users except external-permission users, service
accounts and the anonymous user. Cloud counts `UserTenantMapping` rows. User
creation calls `backend/onyx/auth/users.py:enforce_seat_limit`. On self-hosted,
it checks the license, and no license means no limit. On cloud,
`enforce_cloud_seat_limit` bills the extra seat, and trial tenants skip it.

**Blocking a lapsed deployment.**

| Deployment | Middleware | Blocks when | Allowlist |
|---|---|---|---|
| Self-hosted | `license_enforcement_middleware` | `GATED_ACCESS`, or used seats above seats | `LICENSE_ENFORCEMENT_ALLOWED_PREFIXES` |
| Cloud | `tenant_id_middleware` | tenant in the `gated_tenants` Redis set, which the control plane writes | `MULTI_TENANT_GATING_ALLOWED_PREFIXES` |

The web client blocks pages separately, through
`web/src/components/GatedContentWrapper.tsx:ALLOWED_GATED_PATHS`.

**Community downgrade.** `POST /license/downgrade`
(`backend/ee/onyx/server/license/api.py:downgrade_to_community`) runs only while
`is_access_gated` is true, the same rule that sets `GATED_ACCESS` in settings. In
one commit (`backend/ee/onyx/db/community_downgrade.py`):
- `make_all_cc_pairs_public__no_commit` sets every pair that is not PUBLIC to
  PUBLIC, clears the sync options and timestamps, deletes the data-access group
  links and the external group rows, clears the external ACL columns on documents
  and hierarchy nodes, and marks the pairs' documents for the metadata sync.
  Chunk ACLs stay old until that sync runs ([[document-index]]). A permission sync
  already in flight can write some rows back; they grant nothing on a public pair.
- `remove_custom_user_groups__no_commit` deletes the non-default groups directly,
  not through group sync. First it makes their shared agents, document sets, LLM
  providers, MCP servers and skills public. Members who held admin rights through
  a removed group join Admin, and members left in no default group join Basic.
- `disable_paid_features__no_commit` deletes token budgets, marks hooks deleted,
  turns off standard answers, sets every SCIM token inactive and removes API keys
  through `backend/onyx/db/api_key.py:remove_all_api_keys__no_commit`.

Then `downgrade_to_community` clears the LLM provider listing cache (listings are
cached per group set), resets the enterprise settings, clears chat retention and
deletes the license. The enterprise settings reset
(`backend/ee/onyx/server/enterprise_settings/store.py:reset_settings`) also
deletes the custom analytics script and both logo files.

---

## Contracts and traps

1. `failure-directions-differ` **The failure directions differ on purpose.**
   `backend/ee/onyx/server/middleware/license_enforcement.py:license_enforcement_middleware`
   fails open on a cache error, so a Redis outage does not lock out every user.
   `backend/ee/onyx/server/settings/api.py:apply_license_status_to_settings`
   fails closed, so the UI hides paid features.
   `backend/ee/onyx/utils/tier.py:get_tier` returns `COMMUNITY` on a self-hosted
   DB error and `BUSINESS`, the cloud floor, on a cloud Redis or control-plane
   error. Cloud gating
   (`backend/ee/onyx/server/tenants/product_gating.py:is_tenant_gated`) also
   fails open. Do not
   make a request blocker fail closed on a transient error.
2. `no-tier-license-is-enterprise` **A license with no `customer_tier` resolves to
   `ENTERPRISE`.** `backend/ee/onyx/utils/tier.py:tier_from_license_metadata`
   does this for licenses issued
   before the field existed. An unknown cloud tier resolves to `BUSINESS`
   (`_cloud_tier`). The two defaults differ on purpose.
3. `recovery-paths-reachable` **Keep every recovery path reachable while
   gated.** The self-hosted
   `backend/ee/onyx/configs/license_enforcement_config.py:LICENSE_ENFORCEMENT_ALLOWED_PREFIXES`
   must keep billing, `/license`, auth and user management. The cloud
   `backend/ee/onyx/configs/multi_tenant_gating_config.py:MULTI_TENANT_GATING_ALLOWED_PREFIXES`
   must keep billing, the `/tenants` billing routes and auth. The web
   `web/src/components/GatedContentWrapper.tsx:ALLOWED_GATED_PATHS` must keep
   `/admin/billing` and `/admin/users`. If you rename the billing route without
   the allowlists, an expired customer cannot reach the page that fixes it.
4. `proxy-serves-old-versions` **The `/proxy` endpoints serve every self-hosted
   version in the field.** `backend/ee/onyx/server/tenants/proxy.py` runs on
   cloud at the newest version, and older instances call it. Change its request
   and response shapes only in a compatible way.
5. `two-seat-counts` **Two seat counts exist, and one filter defines a seat.**
   Writes check the live count from `get_used_seats`. The middleware reads
   `used_seats` from the cached license metadata. A path that adds or removes a
   counted user must invalidate the license cache
   (`backend/onyx/auth/users.py:_invalidate_license_cache_after_seat_change`), or
   the 402 decision uses a stale count. The per-user predicate
   `backend/ee/onyx/db/license.py:user_counts_toward_seats` mirrors the
   `get_used_seats` query. Change both together.
6. `seat-lock-before-write` **A check followed by a user write must hold the seat
   lock.** Call `backend/onyx/auth/users.py:enforce_seat_limit_locked` on the
   session that writes the user. It takes
   `backend/ee/onyx/db/license.py:acquire_seat_lock` until commit. Without it, two concurrent signups
   can both pass the check.
7. `paid-rows-join-downgrade` **A paid feature whose rows keep taking effect must
   join the downgrade.** After a downgrade, the tier gate refuses the feature's
   admin route, so an admin cannot turn off what is left. Add the rows to
   `backend/ee/onyx/db/community_downgrade.py:disable_paid_features__no_commit`.
8. `downgrade-deletes-license-last` **The downgrade deletes the license last.** A
   failure before that leaves a licensed deployment part way to Community, and a
   retry finishes it.
9. `checkout-claim-keeps-tenant` **A claim with a `session_id` must keep the
   stored tenant.**
   `backend/ee/onyx/utils/license.py:verify_and_store_license` with
   `keep_stored_tenant=True` stops a
   checkout id from replacing this instance's license with another customer's.
10. `cloud-rejects-only-mutations` **Only claim, upload, delete and downgrade
    reject on cloud.** `GET /license`, `GET /license/seats` and
    `POST /license/refresh` have no `MULTI_TENANT` check.
11. `invalidate-billing-cache` **Mutations must call
    `invalidate_billing_info_cache`.**
    (`backend/ee/onyx/server/billing/api.py:invalidate_billing_info_cache`) It clears the 5-minute admin billing cache
    and, on cloud, the trial-status cache that usage limits read. Without it, a
    trial converted to paid keeps trial limits for up to a full TTL.
12. `two-gated-rules` **"Gated" has two self-hosted rules.** The middleware
    blocks only on a license in `GATED_ACCESS`.
    `backend/ee/onyx/server/settings/api.py:is_access_gated` also counts a
    deployment with no license and a permission-synced pair, and it treats a DB
    error in that check as gated. In that state the UI shows the
    access-restricted screen and offers the downgrade, but the API does not return
    402.

---

## Decisions

- **The license blob is the self-hosted credential.** A self-hosted instance
  holds no control-plane secret. The cloud proxy accepts the signed license, and
  accepts an expired one for checkout, portal and billing reads, so a lapsed
  customer can still pay.
- **The license is stored raw and parsed on read.** The signature stays
  verifiable, and the parsed form lives only in the cache.
- **The downgrade makes data public instead of deleting it.** Community has no
  groups or private connectors. Public access keeps every document reachable, and
  no user loses read access.
- **The self-hosted circuit breaker.** A 502, 503 or 504 from the billing
  information fetch opens a one-hour Redis flag (`billing_circuit_open`). An
  instance that cannot reach Stripe does not wait on a timeout at each page load.

---

## Known issues

- **A user-restricted MCP server stays private after the downgrade.** Only
  servers with group grants become public. A standard image still lets an admin
  edit it. On the MIT-only build, every access edit to it fails with
  `EE_REQUIRED` until an admin makes it public ([[mcp-and-custom-tools]]).
- **Some license changes do not clear the billing cache.** `upload_license`,
  `delete_license`, `refresh_license_cache_endpoint` and `downgrade_to_community`
  do not call `invalidate_billing_info_cache`. The admin page can show the old
  plan for up to 5 minutes.
- **Cloud billing uses two API paths.** The web client calls `/api/tenants` on
  cloud for most billing calls, but `end-trial` uses `/api/admin/billing`
  (`web/src/lib/billing/svc.ts:endTrial`).

---

## Dependencies

- [[editions-and-gating]]: the tier order, and the dispatcher that CE code uses to
  reach the seat checks.
- [[multi-tenancy]]: `MULTI_TENANT` selects the backend, and tenant ids key the
  caches.
- [[authorization]]: `FULL_ADMIN_PANEL_ACCESS` gates the billing and license admin
  routes.
- [[access-control]]: the downgrade removes groups and the grants they carry.
- [[cc-pairs-and-creds]]: the downgrade makes every pair public.
- [[document-index]]: the metadata sync that rewrites chunk ACLs after the
  downgrade.

---

## Recipes

- `add-paid-feature-to-downgrade` **Add a paid feature to the Community downgrade.** Copy the hooks or standard
  answers step in
  `backend/ee/onyx/db/community_downgrade.py:disable_paid_features__no_commit`.
  For a `Settings` field, copy
  `backend/onyx/server/settings/store.py:clear_chat_retention` and call it from
  `downgrade_to_community`. Add a case to
  `backend/tests/external_dependency_unit/ee/onyx/db/test_community_downgrade_paid_features.py`.
  List the paid route prefixes, which bound what can need this, in
  `backend/ee/onyx/configs/license_enforcement_config.py:PATH_PREFIX_MIN_TIER`.
- `add-billing-mutation` **Add a billing mutation.** Copy the seat update in
  `backend/ee/onyx/server/billing/api.py:update_seats`: proxy the call, then call
  `invalidate_billing_info_cache` ([[#invalidate-billing-cache]]). It does not
  store a license, because the control plane may still be reissuing it; on
  self-hosted, the web client calls `/license/claim` after a short delay. List
  the routes with `git grep -n "@router" backend/ee/onyx/server/billing/api.py`.
- `change-proxy-endpoint` **Change a `/proxy` endpoint.** Add fields; do not rename or remove them
  ([[#proxy-serves-old-versions]]). An older instance must still parse the new
  response.
- `load-license-locally` **Load a license locally.** Set `ONYX_DEV_LICENSE` to a signed license and run
  `python -m scripts.seed_dev_license` from `backend/`
  (`backend/scripts/seed_dev_license.py:main`). The script checks the signature
  and stores the license. With an empty value it does nothing.
- `investigate-access-restricted` **Investigate an access-restricted screen.** Check which rule set
  `GATED_ACCESS` ([[#two-gated-rules]]). `GET /api/license` shows the stored
  license and its status. If there is no license, look for a permission-synced
  pair: that alone gates the UI without a 402. On cloud, check whether the tenant
  is in the `gated_tenants` Redis set.
- `reproduce-seat-breach` **Reproduce a seat breach.** On a self-hosted build with a license, add active
  users until used seats exceed the license seats, then send a request outside
  the allowlist. It must return 402 `seat_limit_exceeded`.

---

## Verification

- Unit tests: `backend/tests/unit/ee/onyx/server/billing/`,
  `backend/tests/unit/ee/onyx/server/license/`,
  `backend/tests/unit/ee/onyx/server/tenants/`,
  `backend/tests/unit/ee/onyx/server/settings/`,
  `backend/tests/unit/ee/onyx/server/middleware/`,
  `backend/tests/unit/ee/onyx/db/` and `backend/tests/unit/ee/onyx/utils/`.
- Web: `web/src/app/admin/billing/` and `web/src/lib/billing/` hold the page and
  service tests.
- Downgrade: the `test_community_downgrade*` tests in
  `backend/tests/external_dependency_unit/ee/onyx/db/`.
- No Playwright test covers checkout. By hand: on a self-hosted build with no
  license, open the billing page and start checkout. It must redirect to Stripe.
  Paste a license into the activation card and confirm that `GET /api/license`
  shows it.
