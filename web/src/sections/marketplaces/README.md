# Shared marketplaces

These components are not wired to product pages yet. S9 still needs page integration and browser acceptance.

## SyncFromGitHubDialog

Supply `open`, `onClose` and `onSyncRequested`. The callback receives a saved marketplace, not completed imports.
The dialog refreshes `SWR_KEYS.marketplaces` after creation. The host can refresh its skill list from the callback.

Repository owner, name, ref and folder are separate fields. Ref is required; slash refs stay intact.
Input changes invalidate previews. Closing unmounts the request session, so stale responses cannot populate another session.
Creation disables submission and user dismissal until the request finishes.

The optional `company` contract contains:

- `controls`: the host's existing sharing controls.
- `ready`: whether the selected defaults are valid and ready to save.
- `create(source)`: an atomic creator that saves the company source and selected defaults together.

Company scope appears only with this contract and global `MANAGE_SKILLS` authority.
Do not implement `company.create` as create followed by an access PATCH.
Personal creation uses the shared client directly. Reset the host's sharing draft when starting a new dialog session.

## MarketplaceList

The list owns its SWR read. Mount it above the host's resource list.
Set `visible={false}` when its host tab is hidden. Pending work polls every three seconds while visible.
Polling only reads status; it never requests another sync.

- `filter(row)` selects shared marketplace rows using kind data the host actually has.
- `getCountLabel(row)` overrides skill counts. Return `null` to hide unsupported counts.
- `onSyncFromGitHub` optionally supplies the list's creation action. Omit it when the page menu owns that action.
- `onChanged` refreshes host resources after accepted mutations, sync completion, source removal, or revision/count changes.
- `onConfigureAccess(row)` opens existing sharing controls for company defaults.

The current API has skill counts only. There are no plugin endpoints or inferred plugin counts.
Keep pending and failed sources visible when defining filters, including sources with zero imported skills.

## MarketplaceDetailDialog

The list opens this dialog; hosts can also mount it with `marketplaceId`, `open` and `onClose`.
It supports the same count, change and access callbacks as the list.
After saving access, the host must revalidate `SWR_KEYS.marketplace(id)` and `SWR_KEYS.marketplaces`.

Retirement review snapshots the proposal's revision and IDs, with names from current detail.
Missing names prevent confirmation. A changed or rejected proposal requires another explicit review.
Remove and Replace login have confirmation screens. Replacement uses the acting user's existing GitHub connection.
Server errors remain visible. Personal-source management authority comes from the management API;
company access controls also require the global permission hook.

## Validation boundary

All requests use `lib/marketplaces/api.ts`. The shared client validates responses with its existing schemas.
Its inferred `Marketplace.provider_config` is currently `unknown`; the summary reuses `marketplaceSourceSchema` to narrow it.
The parent can remove that extra parse after strengthening the client schema inference.
