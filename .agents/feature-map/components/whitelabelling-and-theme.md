# Whitelabelling and Theme

> The admin-configured branding layer: custom app name, logo, header/footer/popup
> content, and whether the "Powered by Onyx" tagline shows. One KV blob per
> tenant, served unauthenticated to every page load because the login page and
> anonymous chat need it before any user is known.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** platform
**Edition:** EE. Reading and rendering the resulting settings is CE code
(`useSettings`, `Logo`), but writing them and the admin page itself are EE-only.
**Owns:**
`backend/ee/onyx/server/enterprise_settings/` (`api.py`, `models.py`,
`store.py`), `web/src/app/ee/admin/theme/` (`page.tsx`,
`AppearanceThemeSettings.tsx`, `Preview.tsx`), `web/src/lib/app/components.tsx:Logo`,
`web/src/lib/settings/hooks.ts`

---

## 1. What the user experiences

An admin at **Appearance & Theming** (`/admin/theme`) can set the application
name, upload a custom logo, choose whether the sidebar shows logo-only,
name-only, or both, write custom header/footer/login-page copy, configure a
first-visit popup or a persistent system announcement banner, and (Enterprise
tier only) add a custom help link. The "Powered by Onyx" line is not an admin setting. An operator hides it with the `HIDE_ONYX_BRANDING` env var, and it takes effect only on the Enterprise tier.
Every one of these is visible to every user of the workspace, including
anonymous chat visitors, immediately after save, without a page reload beyond
the SWR/mutate refresh the save button triggers.

A visitor who has never configured any of this sees the stock Onyx logo,
name, and no extra header/footer/popup content: every field falls back to a
default rather than rendering broken or blank.

---

## 2. Surfaces

### Admin endpoints (router prefix `/admin/enterprise-settings`,
`backend/ee/onyx/server/enterprise_settings/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| PUT | `/admin/enterprise-settings` | `admin_ee_put_settings` | `require_permission(FULL_ADMIN_PANEL_ACCESS)`. Rejects a change to `custom_help_link_url`/`custom_help_link_label` if tier < `Tier.ENTERPRISE` (402), even if the caller crafts the request directly. |
| PUT | `/admin/enterprise-settings/logo` | `put_logo` | Multipart upload. `is_logotype` query param picks logo vs. logotype slot. |
| GET/POST | `/admin/enterprise-settings/scim/token` | `get_active_scim_token`, `create_scim_token` | `FULL_ADMIN_PANEL_ACCESS`. SCIM bearer token management (see [[auth-and-identity]]). Not branding, but it lives in this router. |
| PUT | `/admin/enterprise-settings/custom-analytics-script` | `upload_custom_analytics_script` | Requires `CUSTOM_ANALYTICS_SECRET_KEY` to match; unrelated to visual branding but lives in the same store. |

### Public endpoints (router prefix `/enterprise-settings`,
`backend/ee/onyx/server/enterprise_settings/api.py`, **no auth**)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/enterprise-settings` | `ee_fetch_settings` | Returns the full `EnterpriseSettings` blob. On `MULTI_TENANT`, requires a resolved tenant id (401 otherwise); self-hosted has none of that check. |
| GET | `/enterprise-settings/logo` | `fetch_logo` | Serves the stored logo bytes. 404 if none uploaded. `Cache-Control: no-cache`. |
| GET | `/enterprise-settings/logotype` | `fetch_logotype` | Same, for the wordmark variant. No explicit cache-control header (unlike the logo route). |
| POST | `/enterprise-settings/refresh-token` | `refresh_access_token` | Not public: it needs `current_user_with_expired_token`. It refreshes a linked OAuth identity. |
| GET | `/enterprise-settings/custom-analytics-script` | `fetch_custom_analytics_script` | Returns `None` for an unresolved tenant rather than 500ing. |

These are intentionally public: the login page, the anonymous chat surface,
and every pre-auth screen need the app name and logo before any session
exists. The module docstring on `EnterpriseSettings` says so directly: "don't
put anything sensitive in here, as this is accessible without auth"
(`ee/onyx/server/enterprise_settings/models.py:EnterpriseSettings`).

### Frontend route

`/admin/theme` is rewritten to `web/src/app/ee/admin/theme/page.tsx` by
`web/src/proxy.ts:EE_ROUTES`, which lists `"/admin/theme"` explicitly, and
only when `SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED` is true. The
route additionally requires `Tier.BUSINESS` to be visible in the sidebar
(`ADMIN_ROUTES.THEME.requiredTier`, `web/src/lib/admin-routes.ts`).

### Field-level char limits (both sides)

`backend/ee/onyx/server/enterprise_settings/models.py:APPEARANCE_FIELD_MAX_LENGTHS`
is the source of truth; `web/src/app/ee/admin/theme/page.tsx:CHAR_LIMITS`
duplicates the same numbers for the frontend char counters, with an explicit
comment that the two must be kept in sync and that
`test_appearance_char_limits.py` enforces it.

---

## 3. Data model

- One KV blob, `KV_ENTERPRISE_SETTINGS_KEY`
  (`ee/onyx/server/enterprise_settings/store.py:load_settings`/`store_settings`),
  holding the serialized `EnterpriseSettings` pydantic model. No relational
  table. The KV store is the same tenant-scoped mechanism CE's own settings
  use (`onyx/server/settings/store.py:KV_SETTINGS_KEY`), just a different key
  and a different (EE-only) model.
- Brandable fields, all on `EnterpriseSettings`
  (`ee/onyx/server/enterprise_settings/models.py`): `application_name`,
  `use_custom_logo`, `use_custom_logotype`, `logo_display_style`
  (`LogoDisplayStyle`: `logo_and_name` / `logo_only` / `name_only`),
  `custom_nav_items` (list of `NavigationItem`), `two_lines_for_chat_header`,
  `custom_header_content`, `custom_lower_disclaimer_content`,
  `custom_popup_header`, `custom_popup_content`, `show_first_visit_notice`,
  `enable_consent_screen`, `consent_screen_prompt`, `custom_greeting_message`,
  `custom_login_subtitle`, `custom_help_link_url`, `custom_help_link_label`
  (Enterprise-gated). `hide_onyx_branding` is not a field here any more:
  `load_settings` and `store_settings` drop a legacy stored value. The flag now
  comes from the `HIDE_ONYX_BRANDING` env var through `UserSettings.hide_onyx_branding`
  (`onyx/server/settings/api.py`), true only when the env var is true and the
  tier is at least `Tier.ENTERPRISE`. `Logo` reads it from `useSettings()`.
- Logo bytes are not in this blob. They live in the file store under two
  fixed, tenant-scoped file ids: `_LOGO_FILENAME = "__logo__"` and
  `_LOGOTYPE_FILENAME = "__logotype__"`
  (`ee/onyx/server/enterprise_settings/store.py`), written via
  `get_default_file_store().save_file(..., file_origin=FileOrigin.OTHER)`. See
  [[file-store-and-user-files]] for the store abstraction itself; this
  component only calls it.
- The system announcement banner (`system_announcement_*` fields on the theme
  page's Formik form) is **not** part of `EnterpriseSettings` at all: it is a
  separate resource fetched via `SWR_KEYS.adminBanner` and mutated through
  `/api/admin/banner` (`web/src/app/ee/admin/theme/page.tsx:mutateAdminBanner`).
  It is documented here because the theme page is where an admin edits it,
  but its storage and delivery (including the notification-bell integration,
  `invalidateNotificationCaches`) belong to [[notifications]], not this
  component.

---

## 4. How it works

### 4.1 Save flow

```
ThemePage (web/src/app/ee/admin/theme/page.tsx)
  Formik onSubmit
    if a new logo file was selected:
      PUT /api/admin/enterprise-settings/logo (multipart)   -> put_logo -> upload_logo
    PUT /api/admin/enterprise-settings (JSON, merged with existing values)
        -> admin_ee_put_settings -> tier check on 2 fields -> store_settings
    if system_announcement fields changed:
      PUT/DELETE /api/admin/banner  -> separate resource, not EnterpriseSettings
    on success: mutate(SWR_KEYS.enterpriseSettings), toast
```

### 4.2 Read flow (CE code, used by every page)

```
useSettings() (web/src/lib/settings/hooks.ts)
  fetches /api/enterprise-settings (public, ee_fetch_settings) via SWR
  logoUrl = enterprise?.use_custom_logo
      ? `/api/enterprise-settings/logo?v=${logoBuster}`   (logoBuster busts the
                                                             browser cache on every
                                                             SWR data change)
      : null
  appName = enterprise?.application_name?.trim() || "Onyx"
```

`Logo` (`web/src/lib/app/components.tsx:Logo`) is the single component that
actually renders the branding: it reads `logoUrl` and `enterprise` from
`useSettings()`, falls back to `SvgOnyxLogo`/`SvgOnyxLogoTyped` (the stock
Onyx marks) whenever `logoUrl` is null, and switches on
`logo_display_style` to decide whether to render the logo, the name, or both.
An `onyxBranded` prop lets a caller force the stock Onyx mark regardless of
white-label settings, for Onyx-owned surfaces like Craft
(`web/src/lib/app/components.tsx:LogoProps.onyxBranded`).

Custom header/footer/popup content is read directly off `useSettings()` at
the point of use: `web/src/layouts/chromes/AppChrome.tsx` reads
`custom_header_content`; `web/src/app/app/components/AppPopup.tsx` reads
`enable_consent_screen`, `show_first_visit_notice`, `custom_popup_header`,
`custom_popup_content`. Settings are additionally fetched server-side
(`web/src/lib/settings/svcSS.ts:fetchEnterpriseSettingsSS`,
`fetchSettingsSS`) for layouts that need branding in the initial server-rendered
HTML rather than waiting on a client SWR round trip.

### 4.3 Logo upload and validation

```
put_logo(file, is_logotype)                          enterprise_settings/api.py
  -> upload_logo(file, is_logotype)                   enterprise_settings/store.py
       filename extension check (.png/.jpg/.jpeg)     -> 400 INVALID_INPUT otherwise
       read up to MAX_LOGO_SIZE_BYTES + 1 bytes        -> 413 PAYLOAD_TOO_LARGE if over 5 MiB
       sniff_logo_mime_type(bytes):
         puremagic sniff -> must be image/png or image/jpeg (ALLOWED_LOGO_MIME_TYPES)
         Pillow Image.open -> width*height > MAX_LOGO_PIXELS (4096x4096) -> reject
         image.verify() -> reject if it doesn't decode
       file_store.save_file(file_id=__logo__ or __logotype__, file_origin=OTHER)
```

Serving (`_logo_response`, `enterprise_settings/api.py`) runs every fetched
logo through `resolve_inline_disposition` with
`inline_types=ALLOWED_LOGO_MIME_TYPES` and `fallback_media_type="image/png"`,
so even a stored file whose sniffed type has drifted is served as an inert
raster, never as `image/svg+xml` or `text/html`.

---

## 5. Contracts and invariants

1. **A missing custom asset falls back to the stock Onyx branding, never to a
   broken image or blank text.** `Logo` renders `SvgOnyxLogo`/`SvgOnyxLogoTyped`
   whenever `logoUrl` is null (`use_custom_logo` false, or no logo ever
   uploaded); `appName` falls back to the literal string `"Onyx"`
   (`web/src/lib/settings/hooks.ts`). A 404 from `GET /enterprise-settings/logo`
   is expected and handled at the settings layer, not by `Logo` itself
   catching an image load error.
2. **Every uploaded logo is size- and dimension-bounded before it is decoded
   or stored.** `MAX_LOGO_SIZE_BYTES` (5 MiB) bounds the read; `MAX_LOGO_PIXELS`
   (4096x4096) bounds the decoded raster, checked from the header before a
   full decode, specifically because a small, highly compressed file can
   still decode to a much larger bitmap
   (`ee/onyx/server/enterprise_settings/store.py:sniff_logo_mime_type`
   comment). Any change to logo handling must keep both bounds; removing the
   pixel check re-opens a decompression-bomb path even with the byte cap
   intact.
3. **Only PNG and JPEG are ever accepted or served for the logo/logotype,
   never SVG.** The comment in `store.py` states the reason explicitly: the
   logo is served unauthenticated from the app origin, so an SVG or HTML body
   stored there would execute as an active document rather than render as a
   static image.
4. **Writing `custom_help_link_url`/`custom_help_link_label` is blocked
   server-side below `Tier.ENTERPRISE`, independent of what the frontend
   disables.** `admin_ee_put_settings`
   diffs the incoming values against `load_settings()` and 402s
   (`FEATURE_NOT_AVAILABLE`) only for a change to those two fields; every
   other appearance field (logo, app name, header/popup/banner content) is
   writable at any tier once EE code is loaded and the admin page is
   reachable at all (see §9 on where the *real* gate for those other fields
   sits).
5. **A stored appearance string over its current length cap is trimmed on
   load, not rejected.** `_clamp_appearance_fields` in `store.py` exists so
   that lowering `APPEARANCE_FIELD_MAX_LENGTHS` after data was written under a
   larger (or no) cap does not make `ee_fetch_settings` raise for every
   caller, including the unauthenticated ones; it logs a warning and trims
   instead. Re-saving the theme form after such a trim persists the shortened
   value.
6. **`GET /enterprise-settings` and the logo/logotype GETs require no
   authentication by design**, because pre-auth surfaces (login page,
   anonymous chat) need branding before a session exists. Do not add a
   permission dependency to these without also solving that pre-auth
   rendering need; the model's own docstring is the standing warning against
   putting anything sensitive in this blob.
7. **`custom_nav_items` is round-tripped, not editable, in the current
   `/admin/theme` UI.** The Formik submit passes
   `enterpriseSettings?.custom_nav_items || []` straight through unchanged
   (`web/src/app/ee/admin/theme/page.tsx`); there is no form control for it.
   A change to the save payload that drops this field would silently erase
   any `custom_nav_items` set through another path (e.g. a direct API call).

---

## 6. Relationships

**Depends on**
- [[editions-and-gating]]: the entire `/admin/enterprise-settings` write path
  and the `/admin/theme` page are EE-only; `get_tier`/`tier_at_least` gate the
  two Enterprise-only fields exactly as billing's tier checks do (see
  [[billing]] §4.1 for the shared `get_tier` mechanics). `createLogoIcon` in
  `web/src/components/icons/icons.tsx`, called out in `web/AGENTS.md` as the
  one sanctioned exception to "never import from `web/src/components/`" and
  "no `dark:` modifier," is **not** the mechanism that renders the admin's
  custom logo (it builds static connector/service brand icons like
  `BoxIcon`/`S3Icon`). The custom-logo render path is `Logo`
  (`web/src/lib/app/components.tsx`), which uses a plain `<img>` against the
  `/enterprise-settings/logo` URL. Note the distinction if you go looking for
  where the uploaded logo becomes pixels on screen.
- [[file-store-and-user-files]]: logo/logotype bytes are stored and served
  through the shared file store, keyed by fixed file ids rather than a
  content hash or user-scoped id.
- [[multi-tenancy]]: `ee_fetch_settings` requires a resolved tenant id on
  `MULTI_TENANT`; self-hosted has no such requirement since there is exactly
  one tenant.
- [[notifications]]: the system announcement banner edited on this page is a
  separate resource and cache (`SWR_KEYS.adminBanner`), not part of
  `EnterpriseSettings`.

**Depended on by**
- [[chat-frontend]] and every pre-auth page (`AppChrome`, `AppPopup`, the
  login page): all read branding through `useSettings()`/`Logo` rather than
  fetching `EnterpriseSettings` themselves.
- [[observability]]: none directly; this component has no tracing hooks of
  its own beyond standard request logging.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new brandable field to `EnterpriseSettings` | whether it needs a length cap in both `APPEARANCE_FIELD_MAX_LENGTHS` and `web/src/app/ee/admin/theme/page.tsx:CHAR_LIMITS`; `test_appearance_char_limits.py` |
| changes `ALLOWED_LOGO_MIME_TYPES`, `MAX_LOGO_SIZE_BYTES`, or `MAX_LOGO_PIXELS` | `sniff_logo_mime_type` and `_logo_response`'s `resolve_inline_disposition` call, both of which assume the allowlist stays raster-only |
| changes which fields are Enterprise-tier-gated in `admin_ee_put_settings` | the frontend's own disabled-state logic in `AppearanceThemeSettings.tsx` must match, or the UI will show an editable control that 402s on save |
| changes the public `/enterprise-settings*` routes to require auth | every pre-auth surface that reads branding before a session exists (login page, anonymous chat); this is a deliberate design point, not an oversight (§5 point 6) |
| changes `web/src/proxy.ts:EE_ROUTES` | whether `/admin/theme` still rewrites to `web/src/app/ee/admin/theme/`; removing it from the list 404s the route entirely rather than falling back to a CE page (there is no `web/src/app/admin/theme/`) |
| changes the system announcement banner's storage or delivery | this is [[notifications]]'s surface, not this component's; do not duplicate its contract here |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/ee/onyx/server/enterprise_settings/test_logo_upload.py
cd backend && uv run pytest tests/unit/ee/onyx/server/enterprise_settings/test_logo_serving.py
cd backend && uv run pytest tests/unit/onyx/server/test_appearance_char_limits.py
cd backend && uv run pytest tests/external_dependency_unit/ee/onyx/server/enterprise_settings/test_custom_analytics_script.py
```

Playwright e2e:

```bash
cd web && bun run playwright tests/e2e/admin/theme/appearance_theme_settings.spec.ts
```

This spec (`web/tests/e2e/admin/theme/appearance_theme_settings.spec.ts`) logs
in as admin, navigates to `/admin/theme`, and exercises application name,
greeting message, header/footer content, first-visit notice, consent screen,
and custom help link fields end to end; it is gated on an active EE license
via the `eeFeatures` fixture and skips otherwise. No playwright coverage
exists for logo upload specifically.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Log in as `admin_user@example.com` / `TestPassword123!`, go to
   `http://localhost:3000/admin/theme`.
3. Upload a logo, set an application name, save. Confirm the sidebar and
   login page (open in an incognito tab) both reflect the change without a
   full deploy.
4. `curl -I http://localhost:3000/api/enterprise-settings/logo` with no auth
   cookie; confirm it succeeds (public route) and returns an image
   content-type.
5. Try uploading a >5 MiB file, then a renamed `.png` that is actually HTML;
   confirm both are rejected (413 and 400 respectively) rather than stored.
6. On a Business-tier (not Enterprise) license, confirm the custom help link
   control is disabled in the UI, and that a direct PUT with that field
   changed returns 402. Confirm "Powered by Onyx" stays visible unless
   `HIDE_ONYX_BRANDING=true` and the tier is Enterprise.

---

## 9. Footguns

- **`web/src/app/ee/admin/theme/` is the live page.** `web/src/proxy.ts:EE_ROUTES`
  lists `"/admin/theme"` and rewrites it to `/ee/admin/theme`, and there is no
  `web/src/app/admin/theme/` to shadow it. A directory under `ee/admin/` that is
  not in `EE_ROUTES` is unreachable. Check `EE_ROUTES` and whether a CE-tree
  sibling exists before you decide which copy of an admin surface runs.
- **The rewrite only fires when `SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED`
  is true**, which (per `web/src/lib/constants.ts`) mirrors the backend's
  `LICENSE_ENFORCEMENT_ENABLED` default-true behavior described in
  [[editions-and-gating]]. With both flags at their defaults this is always
  true in a standard deployment; an operator who explicitly disables both
  loses the `/admin/theme` route entirely (404, since there is no CE
  fallback page), not a degraded CE version of it.
- **`createLogoIcon` is a false lead for "where is the custom logo
  rendered."** It is real, it is the one sanctioned exception in
  `web/AGENTS.md` to the `web/src/components/` import ban and the `dark:`
  modifier ban, and it is used for third-party connector icons
  (`BoxIcon`, `BraintrustIcon`, `S3Icon`, etc.) in
  `web/src/components/icons/icons.tsx`. It has nothing to do with the
  admin-uploaded white-label logo, which renders through `Logo`
  (`web/src/lib/app/components.tsx`) as a plain `<img src={logoUrl}>`.
- **The logo URL never changes; only its query string does.** `useSettings()`
  appends `?v=${logoBuster}`, a `Date.now()` recomputed on every new SWR
  enterprise-settings payload, purely to defeat browser caching after a
  re-upload. The backend route itself has no version or hash in the path.
- **The logotype GET has no explicit `Cache-Control` header, unlike the logo
  GET's `no-cache`.** `fetch_logotype_helper` passes `cache_control=None` to
  `_logo_response`; a change intended to make logo and logotype caching
  consistent must touch both call sites.
- **The system announcement banner looks like a theme setting but is not
  stored in `EnterpriseSettings`.** It is fetched and mutated as its own
  resource; a change to `EnterpriseSettings`'s serialization or storage will
  not affect it, and vice versa.

---

Cross-links: [[editions-and-gating]], [[billing]], [[multi-tenancy]],
[[auth-and-identity]], [[rate-and-usage-limits]], [[observability]],
[[file-store-and-user-files]], [[notifications]], [[chat-frontend]]
