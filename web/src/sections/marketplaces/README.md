# Shared marketplaces

Both Skills pages mount the shared list and dialog. Browser acceptance and retired-skill management remain pending.

## SyncFromGitHubDialog

Supply `open`, `onClose` and `onSyncRequested`. The callback receives a saved marketplace, not completed imports.
The dialog refreshes `SWR_KEYS.marketplaces` after creation. The host can refresh its skill list from the callback.

Repository owner, name, ref and folder are separate fields. Ref is required; slash refs stay intact.
Input changes invalidate previews. Closing unmounts the request session, so stale responses cannot populate another session.
Creation disables submission and user dismissal until the request finishes.

Company scope appears only for global `MANAGE_SKILLS` holders.
The dialog owns `useCompanyMarketplaceAccess(DEFAULT_COMPANY_MARKETPLACE_ACCESS)` in its open session.
It submits source and access defaults in one `createMarketplace` request. There is no follow-up access PATCH.
Closing resets the company draft. The host does not supply a creator or access controls.

## CompanyMarketplaceAccessControls

Mount `useCompanyMarketplaceAccess(initialDraft)` in the host's creation session.
Pass its result as `<CompanyMarketplaceAccessControls access={access} disabled={saving} />`.
The hook owns a complete `MarketplaceAccessDraft`; subsequent initial values do not replace user edits.
Unmount or key the session on close/reopen. Keep controls disabled throughout creation.

`DEFAULT_COMPANY_MARKETPLACE_ACCESS` explicitly selects organization Viewer access, Available installation, and no groups.
The controls display that choice before creation. Hosts can supply another explicit initial draft.
`marketplaceAccessDraft(snapshot)` converts snapshot `user_group_id` values to request `group_id` values, retaining group policies.

The shared dialog uses `access.ready` and submits `createMarketplace({ ...source, personal: false, access: access.draft })`.
Never create first and PATCH defaults afterward. No direct-user grants are supported.

Readiness requires global `MANAGE_SKILLS` and loaded settings with a known tier.
Community permits organization Viewer access without groups. Incompatible stored defaults stay visible and cannot be saved.
Settings errors disable edits and save; they never imply Community.
Group lookup failures disable additions. Existing IDs and group policies remain in the draft and submission.
Users can explicitly edit or remove an unresolved group grant on a paid plan.

## CompanyMarketplaceAccessModal

Supply `marketplaceId`, `open`, `onClose`, and optional `onSaved(marketplace)`.
Use the list/detail `onConfigureAccess(row)` callback to select the ID and open this modal.
Only global `MANAGE_SKILLS` holders can load defaults. Personal sources cannot use this modal.

Each opening uses a session SWR key and waits for a fresh detail read before copying defaults into the draft.
Background refresh never overwrites edits. Close/reopen or a different ID starts a new session.
Load failures disable save. PATCH failures retain the draft and show the server error inline.
Saving disables the controls, duplicate submits, Cancel, Escape, outside dismissal, and the header close action.

A successful save calls `updateMarketplaceAccess({ id, access: draft })` once, then revalidates
`SWR_KEYS.marketplaces` and `SWR_KEYS.marketplace(id)` through the current SWR provider.
It calls `onSaved(savedMarketplace)` and `onClose()` only after PATCH succeeds.
The host must set `open=false` in `onClose` and refresh Skills from `onSaved`.
Failed saves do not invoke these callbacks or refresh source counts and active Skills.

## MarketplaceList

The list owns its SWR read. Mount it above the host's resource list.
Set `visible={false}` when its host tab is hidden. Pending work polls every three seconds while visible.
Polling only reads status; it never requests another sync.

- `filter(row)` selects shared marketplace rows using kind data the host actually has.
- `getCountLabel(row)` overrides skill counts. Return `null` to hide unsupported counts.
- `onSyncFromGitHub` optionally supplies the list's creation action. Omit it when the page menu owns that action.
- `onChanged` refreshes host resources after accepted mutations, completed work, source removal, and revision or count changes.
- `onConfigureAccess(row)` closes detail before the host opens `CompanyMarketplaceAccessModal` for company defaults.

The current API has skill counts only. There are no plugin endpoints or inferred plugin counts.
Keep pending and failed sources visible when defining filters, including sources with zero imported skills.

## MarketplaceDetailDialog

The list opens this dialog; hosts can also mount it with `marketplaceId`, `open` and `onClose`.
It supports the same count, change and access callbacks as the list.
`CompanyMarketplaceAccessModal` revalidates detail and list caches after saving. Custom access UIs must do the same.

Retirement review snapshots the proposal's revision and IDs, with names from current detail.
Missing names prevent confirmation. A changed or rejected proposal requires another explicit review.
Remove and Replace login have confirmation screens. Replacement uses the acting user's existing GitHub connection.
Server errors remain visible. Personal-source management authority comes from the management API;
company access controls also require the global permission hook.

## Validation boundary

All requests use `lib/marketplaces/api.ts`. The shared client validates responses with its existing schemas.
Its inferred `Marketplace.provider_config` is currently `unknown`; the summary reuses `marketplaceSourceSchema` to narrow it.
The parent can remove that extra parse after strengthening the client schema inference.
