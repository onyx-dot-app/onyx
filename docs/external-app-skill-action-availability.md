# Inject per-action availability into external-app skill files

## Issues to Address

External-app skills (Slack, Linear, Gmail, Google Calendar) ship a static
`SKILL.md` that describes every action the helper script can perform. The agent
running in the sandbox has no idea which of those actions the admin has actually
enabled — that knowledge lives only in the `ExternalAppPolicy` table and is
enforced lazily at egress by the sandbox proxy gate. The result: the agent
happily attempts actions that are policy-`DENY`d, only to be blocked at call
time (wasted turns, confusing failures).

We want the skill file to state, per provider, which actions are available and
which are disabled — rendered per-user from the effective policy at push time.
Example: the Slack SKILL.md should say "List channels, Read channel messages,
Search messages are enabled; Post a message is disabled."

## Important Notes

- **The rendering mechanism already exists.** `company-search` is a templated
  built-in: its on-disk file is `SKILL.md.template`, and `skills/push.py`
  →`_render_template()` substitutes a `{{AVAILABLE_SOURCES_SECTION}}` placeholder
  per user via `skills/rendering.py:render_company_search_skill()`. We follow the
  same pattern for external-app skills. `has_template` is derived from the
  presence of `SKILL.md.template` on disk (`built_in.py`), and `_is_excluded`
  already skips raw `.template` files from the static copy — so converting a
  provider's `SKILL.md` → `SKILL.md.template` automatically routes it through
  `_render_template`.

- **Effective policy is already computed.** `external_apps/providers/registry.py`
  →`action_policy_views(app_type, stored)` merges the code catalog with the
  admin's sparse stored overrides and returns one `ActionPolicyView` per catalog
  action with the effective `state` (`ALWAYS` / `ASK` / `DENY`). We reuse this
  verbatim — no new policy-resolution logic.

- **Mapping skill → app_type → policies.** An external-app built-in `Skill` row
  has `built_in_skill_id` (e.g. `"slack"`). `EXTERNAL_APP_BUILT_IN_SKILL_IDS`
  (`built_in.py`) maps `app_type → skill_id`; we add the inverse so the renderer
  can go `built_in_skill_id → app_type`. The `ExternalApp` row links to the skill
  via `ExternalApp.skill_id`; `db/external_app.py:get_policies(app_id)` returns
  the stored overrides. There is no getter by `skill_id` yet — add one.

- **Availability semantics:** `DENY` = disabled; `ALWAYS`/`ASK` = available
  (an `ASK` action *can* be used, it just prompts for approval). We render two
  groups — Available and Disabled — and annotate `ASK` actions as
  "requires approval" so the agent can prefer auto-approved paths. This matches
  the gate's actual behavior and the user's "enabled / disabled" framing.

- **The skill file is a hint, not the enforcement boundary.** The proxy gate
  remains the source of truth. If policy changes after a sandbox is hydrated the
  file is stale until the next push;
  `push_skill_to_affected_sandboxes` already re-pushes filesets on skill changes.
  (Wiring policy-update → re-push is out of scope here; noted as a follow-up.)

- **Atomicity:** converting a provider's `SKILL.md` to `.template` while
  `_render_template` does not yet handle it would drop the file entirely (static
  copy skips `.template`, renderer skips unknown skills). The template conversion
  and the `_render_template` dispatch must land together.

## Implementation Strategy

1. **`db/external_app.py`** — add `get_external_app_by_skill_id(db_session,
   skill_id) -> ExternalApp | None`, eager-loading `policies` (mirrors
   `get_external_app_by_id`).

2. **`skills/built_in.py`** — derive and export
   `EXTERNAL_APP_SKILL_ID_TO_APP_TYPE` (inverse of
   `EXTERNAL_APP_BUILT_IN_SKILL_IDS`).

3. **`skills/rendering.py`** — add `render_external_app_skill(db_session,
   slug, app_type, external_app, skills_dir) -> str`:
   - read `{skills_dir}/{slug}/SKILL.md.template`
   - `stored = get_policies(db_session, external_app.id)` (or `{}` if no app row)
   - `views = action_policy_views(app_type, stored)`
   - split into available (`state != DENY`) and disabled (`state == DENY`);
     annotate `ASK` rows; build a markdown section
   - substitute `{{ACTION_AVAILABILITY_SECTION}}` and return

4. **`skills/push.py`** — extend `_render_template()`: if
   `definition.built_in_skill_id` is in `EXTERNAL_APP_SKILL_ID_TO_APP_TYPE`,
   look up the `ExternalApp` by `skill.id` and render via
   `render_external_app_skill`; keep the company-search branch; keep the warning
   fallback.

5. **Templates** — for `slack`, `linear`, `gmail`, `google-calendar`: rename
   `SKILL.md` → `SKILL.md.template` and insert an
   `## Available actions\n\n{{ACTION_AVAILABILITY_SECTION}}` section near the top
   (after the intro, before Usage). Content otherwise unchanged.

## Tests

External-dependency unit test (needs Postgres for the `ExternalApp` /
`ExternalAppPolicy` / `Skill` rows), added alongside
`tests/external_dependency_unit/craft/test_external_app_fileset.py`:

- Slack app with a policy override setting `MESSAGES_WRITE` → `DENY`, others left
  at their `ALWAYS` defaults; authenticated user. Assert the rendered
  `slack/SKILL.md`:
  - contains the available actions (e.g. "List channels") under the available
    group,
  - lists "Post a message" as disabled,
  - does **not** ship `slack/SKILL.md.template` raw.
- Slack app with no policy overrides: assert the write action falls back to its
  `ASK` default and is rendered as available-with-approval (not disabled).

Existing `test_external_app_fileset.py` (no overrides) must still pass — it only
asserts presence of `slack/SKILL.md` and `slack/slack_api.py`, both still
produced.
