# Onyx Craft Sidebar Cleanup

> **Stacked on `craft-input-bar` (#11634).** This branch builds on the composer
> redesign in that PR — `BaseInputBar`, `CraftInputBar`, `PlusMenuButton`,
> `InputChipStrip`. The Library and model-picker work below extends those
> components rather than rebuilding them.

## Issues to Address

The Craft sidebar has accumulated too many top-level entries and a `Configure`
page that mixes unrelated settings. Today the pinned sidebar shows six entries:

```
Start Crafting · Configure · Scheduled Tasks · Skills · My Apps · Manage Apps
```

Problems:

- **Too many tabs.** `My Apps` and `Manage Apps` are two tabs for one concept
  (apps), split only by admin permission.
- **`Configure` is a grab-bag.** After we rip out `Your Role`, it holds only
  `Default LLM`, `User Library`, and `Connect your data` — too thin to justify a
  top-level tab.
- **`Connect your data`** is admin/curator-only and just deep-links to
  `/admin/indexing/status`. The `ConnectDataBanner` on the welcome screen already
  nudges admins to connect data, so this row is redundant.

Goal: a clean, intuitive sidebar with exactly four tabs:

```
Start Crafting · Scheduled Tasks · Skills · Apps
```

## Design Direction

We took inspiration from how the leading products solve these surfaces:

- **Apps as a directory** (Claude Connectors, ChatGPT Apps): lead with a
  "Connected" list, then a browsable "Browse" grid. Search when the list grows.
- **Personal vs Workspace ownership axis** (Linear, Vercel, GitHub): admin
  org-config lives under a Workspace scope, personal connections under Personal —
  not a flat "manage" tab.
- **Files belong with the work, not in the integrations directory**
  (ChatGPT Projects, Claude knowledge): the persistent User Library moves into the
  composer `+` menu, where users actually think about giving a craft their files.

## Important Notes

Findings from investigating the current code (June 2026):

- **The model is only settable from the Configure page.** There is no model
  picker in the chat input bar today. `BuildLLMPopover` and `useBuildLlmSelection`
  are referenced only by `web/src/app/craft/v1/configure/page.tsx`.

- **Changing the model no longer requires a sandbox rebuild.** Since the
  opencode-serve migration, all configured providers are pre-registered in
  `opencode.json` at provision time, specifically so per-prompt model overrides
  can cross providers without a pod restart:
  - `session/manager.py:130-157` — `get_all_build_mode_llm_configs` registers
    every configured provider; the docstring states overrides cross providers
    "without a pod restart."
  - `sandbox/serve_transport.py:419` → `sandbox/opencode/serve_client.py:1230`
    already thread a per-prompt `body["model"] = {"providerID", "modelID"}`
    override end-to-end.
  - The Configure page rebuilds today only because it stores the model on the
    `BuildSession` row at creation (`_get_session_agent_selection`,
    `manager.py:1645`) and tears down + re-provisions the pre-provisioned session
    on change. `MessageRequest` (`api/models.py:178`) currently has only
    `content` — no per-message model field.

- **opencode.json does not whitelist models.** The `models` block written by
  `sandbox/util/opencode_config.py:115` only attaches per-model *options* (e.g.
  adaptive-thinking config). opencode resolves `{providerID, modelID}` against its
  own catalog, so an input-bar picker can offer multiple models per configured
  provider. Caveat: thinking-option blocks are written only for the
  provision-time default model, so a non-default thinking model picked at runtime
  won't get those tuned options (degrades gracefully).

- **Inherited composer (from #11634).** `CraftInputBar` composes `BaseInputBar`
  with `topSlot` (chip strip) and `bottomLeftSlot` (the `+` button); it does
  **not** use `bottomRightSlot`. `PlusMenuButton` already implements a `+` popover
  with an "Add files or photos" action (per-message attach) and right-anchored
  flyout panels for Skills and Apps via the reusable `FlyoutRow`. The persistent
  **User Library** is *not* yet wired into this menu — it lives in
  `configure/components/UserLibraryModal.tsx`.

- **The two apps pages are distinct jobs.**
  - `apps/page.tsx` ("My Apps") — a user connects their own accounts via OAuth or
    custom credentials so Craft can use them as context.
  - `apps/admin/page.tsx` ("Manage Apps", admin-only) — an admin configures which
    org-wide app integrations exist (built-in providers + custom apps).

## Implementation Strategy

High-level approach. Four coordinated changes:

### 1. Default LLM → model picker in the chat input bar

- **Frontend:** add a model picker to `CraftInputBar`, placed in `bottomLeftSlot`
  next to the `+` button (`[+] [✱ Opus 4.7 ▾]`). Reuse
  `BuildLLMPopover` and `useBuildLlmSelection`. It seeds from the existing cookie
  (still the default for new and pre-provisioned sessions) and is editable per
  session.
- **Backend:** add optional `model` + `provider` fields to `MessageRequest`. In
  `send_message`, when present, use them as the `agent_provider` / `agent_model`
  override (the plumbing already exists) and persist the choice back to the
  `BuildSession` row so a reload keeps it.
- **Remove** the Configure page's rebuild-on-change logic
  (`clearPreProvisionedSession` + `ensurePreProvisionedSession`). Model changes no
  longer re-provision. Pre-provisioning stays seeded by the cookie default.
- Picker lists only models under already-configured providers.

### 2. User Library → composer `+` menu (Library flyout)

- Add a **Library** flyout to `PlusMenuButton` using the existing `FlyoutRow`
  pattern. It lists the user's library files and a **"Manage library…"** action.
- "Manage library…" opens the existing `UserLibraryModal` (relocated out of the
  Configure page; the modal component itself is reused as-is).
- Keeps the Apps page purely about integrations.

### 3. Merge My Apps + Manage Apps into one Apps page (Personal / Workspace)

- One route `/craft/v1/apps` with a **Personal | Workspace** scope toggle at the
  top. Workspace only renders for admins.
- **Personal** (everyone): a search box, a **Connected** list (apps the user has
  authed — green check + Disconnect), then a **Browse** grid of available apps
  (logo card + short description + Connect). This is today's `apps/page.tsx` data,
  re-laid-out as a directory.
- **Workspace** (admin only): today's `apps/admin/page.tsx` content — Configured
  apps (Edit / Disable / delete) and an Add-integration grid + Custom app.
- Scope selection via query param (`?scope=workspace`), defaulting to Personal.
- Keep `/craft/v1/apps/admin` as a redirect into the Workspace scope so existing
  links don't break.

### 4. Drop "Connect your data"

Remove the row entirely. The `ConnectDataBanner` on the welcome screen still nudges
admins, and connectors are managed on the admin page.

### Cleanup

- Delete `configure/page.tsx`, `CRAFT_CONFIGURE_PATH`, and the dead
  model-change re-provision logic.
- Remove the `Configure`, `My Apps`, and `Manage Apps` tabs from `SideBar.tsx`;
  add a single `Apps` tab.

## Final Sidebar

```
┌────────────────────┐
│ ✎ Start Crafting   │
│ ⏱ Scheduled Tasks  │
│ ▦ Skills           │
│ 🔌 Apps            │
│                    │
│ Sessions…          │
├────────────────────┤
│ ← Back to Chat     │
│ 🐞 (debug logs)    │
│ 👤 Account         │
└────────────────────┘
```

## Apps Page (Personal / Workspace)

```
APPS                                         [ View ]
┌─────────────────────────────────────────────────────┐
│  [ Personal ]  [ Workspace ]  (admin only)           │
├─────────────────────────────────────────────────────┤
│  🔎 Search apps…                                      │
│                                                       │
│  CONNECTED                                            │
│  Slack            ✓ Connected            [Disconnect] │
│                                                       │
│  BROWSE APPS                                          │
│  ┌───────────────┐ ┌───────────────┐                 │
│  │ Google Drive  │ │ Notion        │   … grid …       │
│  │ [ Connect ]   │ │ [ Connect ]   │                 │
│  └───────────────┘ └───────────────┘                 │
└─────────────────────────────────────────────────────┘

Workspace (admin): Configured apps + Add-integration grid + Custom app.
```

## Composer Library Flyout

```
CHAT INPUT
┌──────────────────────────────────────────┐
│ Build me a revenue dashboard…             │
│ [ + ] [✱ Opus 4.7 ▾]              [Send]  │
└──┬───────────────────────────────────────┘
   ▸ Add files or photos      (per-message attach — exists)
   ▸ Skills ▸                 (exists)
   ▸ Apps ▸                   (exists)
   ▸ Library ▸  brand-guidelines.pdf        (new)
                q2-financials.xlsx
                Manage library…  → UserLibraryModal
```

## Out of Scope (Known Inconsistency)

Skills and external apps are both "capabilities the Craft agent can reach for,"
but their **admin management lives in two different homes**: skill management is in
the global admin panel (`/admin/skills`), while app management is in the Craft
sidebar (`/craft/v1/apps/admin`, becoming the Workspace scope here). This PR
deliberately does **not** resolve that — it stays focused on the sidebar cleanup.

Noted for a future pass. Two possible directions if/when we unify: bring skill
management into the Craft sidebar with the same Personal/Workspace toggle (treating
skills + apps as one "Craft capabilities" set), or move app management out to the
admin panel (matching Onyx-wide governance convention). Direction intentionally
left open.

## Tests

This is a frontend reorganization plus a small backend field addition. Proposed
coverage (don't overtest):

- **Playwright (E2E):** one test covering the Apps page — Personal scope shows
  Connected + Browse; the Workspace scope is visible to admins only; and the
  `/craft/v1/apps/admin` redirect lands on the Workspace scope.
- **Integration:** one test that `POST /messages` with a `model`/`provider`
  override switches the session's model without re-provisioning (and persists to
  the session row).

The Library flyout and sidebar tab/routing changes are verified by the Playwright
test above plus existing Storybook coverage for `PlusMenuButton`; no extra unit
tests needed.
