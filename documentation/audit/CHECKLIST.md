# Per-page review checklist

Review unit: one MDX page (plus the images it references). Compare against the current Onyx app (running dev stack)
and the feature map in the onyx repo (`.agents/feature-map/components/<component>.md`,
or `components/connectors/<component>.md` for a connector source, listed per page in `audit/manifest.json`).

Audience rule: customer-facing. Describe what a user or admin can do and how.
No internal implementation detail (module names, Celery queues, DB tables)
unless an admin needs it to operate the product. Never document Knowledge Graph as a working feature.

## 1. Copy

- [ ] Title/description match what the feature is called in the current UI.
- [ ] Every UI label, menu path, button, and setting name exists verbatim in the
      current app (check the running stack, then `web/src`).
- [ ] Every step in a flow is still the real order of operations.
- [ ] Every claim about behaviour matches the feature-map component (User
      experience, Architecture, Contracts and traps). Flag edition/tier gating (CE / Business / Enterprise / Cloud)
      where it applies, using the snippet `snippets/enterprise-edition.mdx`.
- [ ] Removed, renamed, or newly added capabilities are reflected
      (e.g. Actions -> Plugins, Assistants -> Agents, Vespa -> OpenSearch).
- [ ] Env vars / config keys exist in `backend/onyx/configs/app_configs.py` (or
      the relevant config module) with the same name and default.
- [ ] Links resolve to pages present in `docs.json` (or redirects).
- [ ] Prose is short, active voice, one idea per sentence.

## 2. Images

For every `<img>` / `![]()` / `<Frame>` on the page:

- [ ] `onyx-ui` images show the current UI (compare to the live stack at the
      same route). Replace if the layout, labels, nav, or theme differ.
- [ ] `connector-mixed` images: vendor-console screenshots stay unless the
      vendor flow changed; Onyx connector-form screenshots follow the `onyx-ui` rule.
- [ ] Image is referenced from a path that exists; alt text describes it.
- [ ] Replacement screenshots: light theme, 1440x900 viewport, admin user,
      saved as PNG under the page's existing `assets/...` directory with the same filename (so the MDX does not change)
      unless the image is new.
- [ ] Remove images for features that no longer exist (and the asset file).

## 3. Record the result

Append one JSON line to `audit/results/<slug>.json`:

```json
{"page": "admins/agents/overview.mdx", "status": "updated|ok|blocked",
 "copy_changes": ["..."], "images_replaced": ["assets/..."],
 "images_flagged": ["assets/... (reason)"], "blocked_on": "EE license|feature unavailable locally|..."}
```
