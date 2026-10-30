# Whitelabelling and Theme

> The admin-set branding layer: application name, logo, greeting, header, footer
> and login text, first-visit notice, consent screen and help link, stored as one
> key-value blob per tenant plus two logo files. The read routes need no login,
> because the login page needs the branding before any user is known.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** EE writes the settings and hosts the admin page. CE frontend code
(`useSettings`, `Logo`) reads and renders them, and treats a missing EE route as
"no branding".

---

## User experience

- **An admin** opens Appearance & Theming (`/admin/theme`). The admin sets the
  application name, uploads a logo, and chooses logo only, name only, or both.
  The admin writes greeting, header, footer and login text, and sets up a
  first-visit notice or a consent screen. On the Enterprise tier the admin can
  also add a custom help link. After a save, the change shows without a
  deploy, for signed-in users and on the login page. The customer guide is
  `documentation/admins/advanced_configs/white_labeling.mdx`.
- **A bad logo upload fails with a clear error:** a file over 5 MB, a file that
  is not a real PNG or JPEG, or an image that is too large in pixels.
- **A visitor** on a workspace with no branding sees the stock Onyx logo and
  the name "Onyx". Every field falls back to a default. Nothing shows broken.
- **"Powered by Onyx"** is not an admin setting. An operator hides it with the
  `HIDE_ONYX_BRANDING` env var. It works only on the Enterprise tier.
- **A CE workspace** has no theme page. A visit to `/admin/theme` redirects to
  the app with a message. The backend holds the admin settings API at the
  Business tier, and the custom analytics script and SCIM token routes under
  it at Enterprise ([[editions-and-gating]]). A lower tier gets a "requires the
  plan" error.
- **The banner API is not tier-gated.** The banner editor is on the theme page,
  but a CE admin can set a banner through the API ([[notifications]]).

---

## Scope

This component owns the enterprise settings record, its store and its public
and admin routes, the logo upload and serving rules, the custom analytics
script (upload needs the `CUSTOM_ANALYTICS_SECRET_KEY` value; the frontend
injects it into every page), the theme admin page, and the render path through
`useSettings` and `Logo`.

Its neighbours own:
- [[notifications]]: the system announcement banner. The theme page edits it,
  but it is a separate resource (`/api/admin/banner`) delivered as a
  notification.
- [[auth-and-identity]]: the SCIM token routes and the `refresh-token` route.
  Both sit on this component's routers, but they are identity features.
- [[file-store-and-user-files]]: the store that holds the logo bytes.
- [[editions-and-gating]]: the EE route rewrite and tier checks in general.
- [[billing]]: the Community downgrade that calls `reset_settings`.

---

## Architecture

**Storage.** `ee/onyx/server/enterprise_settings/store.py` keeps the settings
as one blob under `KV_ENTERPRISE_SETTINGS_KEY` in the tenant's key-value store.
The logo and logotype are file-store files with fixed ids, `__logo__` and
`__logotype__`. `reset_settings` restores stock branding and removes the
analytics script and both logos. `ee/onyx/server/seeding.py:seed_db` can also
write the settings, the nav items and the logo from `ENV_SEED_CONFIGURATION`.

**Write path.** `web/src/app/ee/admin/theme/page.tsx` uploads a new logo first
(`PUT /admin/enterprise-settings/logo`). It then sends the whole settings
object, merged with the stored values, to `admin_ee_put_settings`. Banner
changes go to the banner API in the same submit.

**Read path.** `useSettings` fetches `/api/enterprise-settings` through SWR. It
derives `appName` (blank means "Onyx") and `logoUrl`, which is set only when
`use_custom_logo` is true. `Logo` renders the stock mark when `logoUrl` is
null, or when a caller passes `onyxBranded`, as Craft does. Layouts that need
branding in the first HTML call `web/src/lib/settings/svcSS.ts:fetchSettingsSS`.
Backend email and usage-report code reads `load_runtime_settings`, which fills
in the default application name.

**Admin page gating.** `web/src/proxy.ts:EE_ROUTES` always rewrites
`/admin/theme` to `/ee/admin/theme`. `web/src/app/ee/layout.tsx` gates the page
on `ee_features_enabled`. There is no CE copy of the page.

**False lead.** `createLogoIcon` in `web/src/components/icons/icons.tsx` builds
static connector and service icons. It does not render the uploaded logo.
`web/src/lib/app/components.tsx:Logo` renders it as a plain `<img>`.

---

## Contracts and traps

1. `read-routes-public` **The read routes are public by design.**
   `GET /enterprise-settings`, the logo routes and the analytics script route
   take no auth, because pre-login pages need them. The `EnterpriseSettings`
   docstring forbids anything sensitive in the blob. A new field is public the
   moment it is added. On cloud,
   `ee/onyx/server/enterprise_settings/api.py:ee_fetch_settings` refuses a request that has
   no resolved tenant, and `fetch_custom_analytics_script` returns nothing.
2. `logo-inert-raster` **The logo stays an inert raster.**
   `ee/onyx/server/enterprise_settings/store.py:upload_logo` accepts only PNG
   and JPEG, checked by content in `sniff_logo_mime_type`, not
   by extension alone. The logo is served without auth from the app origin, so
   an SVG or HTML body would run as script there.
   `ee/onyx/server/enterprise_settings/api.py:_logo_response` also clamps
   the served type through `resolve_inline_disposition`. Keep both sides
   raster-only.
3. `logo-size-bounds` **Keep both size bounds and the decode check.**
   `ee/onyx/server/enterprise_settings/store.py:MAX_LOGO_SIZE_BYTES` caps the
   bytes read. `MAX_LOGO_PIXELS` caps the decoded
   size, checked from the header before a full decode, because a small
   compressed file can decode to a huge bitmap.
   `server/runtime/onyx_runtime.py:OnyxRuntime.get_emailable_logo` decodes the
   stored logo with Pillow each time an email is sent, so a body that only has
   PNG magic bytes, or a huge bitmap, fails or stalls email delivery.
   `sniff_logo_mime_type` therefore also runs `verify()`.
4. `write-tier-per-route` **Tier checks on the write path are per route, except
   the help link.** `ee/onyx/server/middleware/tier_gate.py:tier_gate_middleware`
   holds the `/admin/enterprise-settings` routes, logo upload included, at
   `Tier.BUSINESS`, and the analytics script and SCIM routes under it at
   `Tier.ENTERPRISE` (`ee/onyx/configs/license_enforcement_config.py:PATH_PREFIX_MIN_TIER`,
   longest prefix wins). Inside that
   route, only the help link has a field check: `admin_ee_put_settings` refuses
   a change to `custom_help_link_url` or `custom_help_link_label` below
   `Tier.ENTERPRISE`. If the UI disables another field by tier, add the same
   check here, or the API will accept it.
5. `clamp-on-load` **Over-long stored strings are trimmed on load, not
   rejected.**
   `ee/onyx/server/enterprise_settings/store.py:_clamp_appearance_fields` trims each field to
   `APPEARANCE_FIELD_MAX_LENGTHS`. Without it, lowering a cap makes the public
   settings route fail for every caller, and the admin page cannot open to fix
   it. Stored blobs written under an older, higher cap survive a deploy that
   lowers it.
6. `char-limits-both-sides` **The length caps exist on both sides.**
   `CHAR_LIMITS` in the theme page repeats `APPEARANCE_FIELD_MAX_LENGTHS`.
   `backend/tests/unit/onyx/server/test_appearance_char_limits.py` keeps them
   equal, but only for the fields in its own `BACKEND_LIMITS`. A new capped
   field needs both entries and a `BACKEND_LIMITS` entry.
7. `save-sends-whole-object` **The save sends the whole object.**
   `PUT /admin/enterprise-settings` replaces the blob. The page merges the
   stored values into the request and passes `custom_nav_items`,
   `use_custom_logotype` and `two_lines_for_chat_header` through, because the
   page has no control for them. A change that drops a field from the
   payload erases values that seeding or a direct API call set.
8. `ee-layout-fails-open` **The `/ee` layout fails open.** If the settings
   fetch throws, the layout renders the page. When `ee_features_enabled` is
   false and the app is not in `gated_access`, it renders `EEFeatureRedirect`.
   A page under `web/src/app/ee/admin/` that is not in `EE_ROUTES` is reachable
   only at `/ee/admin/...`.
9. `logo-url-cache-buster` **The logo URL never changes; only its query string
   does.** `web/src/lib/settings/hooks.ts:useSettings` adds `?v=<logoBuster>`, a new timestamp for each new
   settings object, to beat the browser cache after an upload. The SWR
   `compare` uses reference equality so that `mutate()` always makes a new
   buster. The logo route sends `Cache-Control: no-cache`, and the logotype
   route sends none.
10. `ce-404-no-branding` **A CE backend returns 404 for the enterprise settings
    route.** `useSettings` treats that 404 as "no branding" and does not retry.
    Do not turn it into an error state.

---

## Dependencies

- [[editions-and-gating]]: the EE router, the `/ee` rewrite, and `tier_at_least`.
- [[file-store-and-user-files]]: logo storage.
- [[multi-tenancy]]: the key-value store and file ids are tenant-scoped.
- [[billing]]: the license tier, and the downgrade that resets branding.

---

## Recipes

- `add-branding-field` **Add a branding field.** Copy `custom_login_subtitle`: a capped free-text
  field that the login page reads. Add it to `EnterpriseSettings` and to the
  web `EnterpriseSettings` type in `web/src/lib/settings/types.ts`. If it is
  free text, add a cap to `APPEARANCE_FIELD_MAX_LENGTHS` and `CHAR_LIMITS`
  ([[#char-limits-both-sides]]). Add a control and a submit entry on the theme
  page ([[#save-sends-whole-object]]). Read it through `useSettings`. Add a
  server tier check if the field is tier-gated ([[#write-tier-per-route]]).
  Give it a default, because stored blobs lack the new key. List the current
  fields in the `EnterpriseSettings` model.
- `investigate-logo-missing` **Investigate "my logo does not show".** Check that `use_custom_logo` is true
  in `GET /api/enterprise-settings`, then that `GET
  /api/enterprise-settings/logo` returns an image. A 404 there means no
  `__logo__` file. A stale image after an upload points at the cache buster
  ([[#logo-url-cache-buster]]). On cloud, a pre-login request with no tenant
  gets no branding ([[#read-routes-public]]).

---

## Verification

- Unit: `backend/tests/unit/ee/onyx/server/enterprise_settings/` (logo upload,
  logo serving, store) and the char-limit parity test in
  `backend/tests/unit/onyx/server/`.
- External dependency: `backend/tests/external_dependency_unit/ee/onyx/server/enterprise_settings/`
  for the custom analytics script.
- Playwright: `web/tests/e2e/admin/theme/`. It needs an EE license and does not
  cover logo upload.
- By hand: upload a logo and set a name, then open the login page in a private
  window and confirm both show. Upload an HTML file renamed to `.png` and
  confirm a 400.
