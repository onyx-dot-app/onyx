# Skills

> Agent Skills: instruction bundles that Onyx renders for each user and pushes into that user's Craft sandbox, and that chat agents list and read (custom skills, and on a deployment with chat VMs the chat built-ins). This component owns skill sharing, installation policy, per-user rendering, the hashed push and the chat skill tools.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE. Group shares need the EE group tables.

---

## User experience

- **A user** opens Customize → Skills (`/app/customize/skills`,
  `sections/customize/CustomizeSkillsPage.tsx`; Craft is not needed, and
  `/craft/v1/skills*` redirect here with their query). The groups are Created by
  you (owner is the user), From your organization (published), Shared with you,
  and Built-in, which shows only with Craft on
  (`lib/customize/skills.ts:groupSkills`). A row has the
  tag Off, Required, Pending review or Unpublished changes, the date, Turn
  on, and a menu (Turn on/off, Share, Remove). Add has Upload skill and Create a
  skill (`/app/customize/skills/new`); GitHub skills come in through a
  marketplace ([[#github-marketplaces]]). A custom skill
  opens at `/app/customize/skills/[id]`; a built-in opens a preview. A custom
  skill's icon is a themed glyph picked from its name and description
  (`sections/customize/skillIcon.tsx`). The Admin Panel lists custom skills
  only.
- **Built-in skills** are always on. A built-in that depends on an unavailable
  service, such as image generation with no provider or the browser with
  `ENABLE_BROWSER` off, is hidden. The built-in skill of a preset app, such
  as Slack or Linear, shows and loads only for a user who runs a plugin that
  holds that app ([[#built-in-app-skill-rule]]). A custom skill written for an
  app is an ordinary custom skill: it loads before the user connects the app.
- **Authoring.** A user writes a skill in the browser editor, or uploads a
  `.zip` or a single SKILL.md. The owner shares with users or groups as
  viewer or editor, publishes to the organization, or transfers ownership.
- **GitHub marketplaces.** A user adds a GitHub repository with a
  `.claude-plugin/marketplace.json` as a marketplace ([[#github-marketplaces]]).
  Each entry becomes one plugin, and "Sync now" brings the repository's
  changes. A personal marketplace belongs to the user who adds it. A company
  marketplace needs organization-wide `MANAGE_PLUGINS` on the user and on the
  token (`server/features/skill/marketplace_api.py:_is_manager`), and the organization
  sees its plugins as it sees published ones, under the marketplace default.
  A synced plugin's content changes only in GitHub. A company plugin's sharing
  and install settings change in Onyx; a personal one has neither. On the web, the Plugins tab Add menu
  (`sections/customize/AddSkillMenu.tsx`) has Add marketplace
  (`sections/marketplaces/AddMarketplaceModal.tsx`: source, then a confirm
  step with the resolved source and each entry's Will install list). A Marketplaces
  section below the plugin list (`CustomizePluginsPage`, `id="marketplaces"`, in
  both panels; `/app/customize/plugins/marketplaces` redirects to the tab) has
  the table (`sections/marketplaces/MarketplacesTable.tsx`); Add marketplace is
  in the Add menu and the empty state only. After an add the menu goes to
  `#marketplaces`, and the section scrolls into view when it mounts under that
  hash. The page holds the one `useMarketplaces` subscription and passes it to
  the table, because each subscription refreshes the skill lists on a sync
  change. The table has failed syncs above it with the error (the Sync cell
  shows only the state and the time),
  a row menu (Sync now, Default Access, Replace login,
  Remove, which names the plugins it deletes) and a detail modal. Members see
  company marketplaces read-only (`can_manage` false: no row menu, no Sync
  now). The confirm step asks for the type before the entries and lists ready
  entries first; the others fold behind one button. On the Plugins tab
  (`lib/plugins/directory.ts`, `lib/customize/plugins.ts`) a synced plugin is
  in "From marketplaces" with "from <marketplace>", and a manager sees another
  user's unshared plugin as "private to <email>", not shared. The plugin page
  shows a "Managed by the <name> marketplace" note with a link to the Marketplaces section. For `content_locked` the web offers no
  content change: no Edit on the skill page, no restore or publish on the
  versions tab, and no organization access or ownership transfer in the share
  dialog (`lib/skills/sharing.ts:canChangeOrganizationAccess`); each says
  why. `can_delete` is false for a synced plugin.
- **Plugin upload.** A user uploads a Claude Code or Codex plugin zip
  ([[#plugin-upload]]). `POST /skills/plugins/inspect` shows the skills, the
  MCP servers the plugin needs with their state for the user, the parts Onyx
  does not use, and the save target. `POST /skills/plugins` saves it. On the
  web, Add > Upload plugin on the Plugins tab of Customize opens
  `web/src/sections/modals/plugins/UploadPluginModal.tsx`; a zip with no
  plugin.json (`lib/plugins/upload.ts:pluginUploadKind`) goes on to the skill
  flow. A dropped folder is zipped in the browser when it has SKILL.md or a
  plugin.json at its top level (`lib/skills/bundleUpload.ts:prepareSkillBundleUpload`
  with `allowPlugin`).
- **Admins** set the installation policy of a custom skill: available (the user
  opts in), installed by default (on until the user opts out), required (on,
  and the user cannot turn it off), or not available (hidden). With no own
  setting ("Default access" in the UI) the skill follows the Organization
  library default; an own `AVAILABLE` overrides a stricter default. This needs
  organization-wide `MANAGE_PLUGINS`, which only admins hold today. A group
  setting (`SkillShareRequest.group_settings`, also on a group with no share)
  replaces the Organization setting for that group's members. It also needs
  organization-wide `MANAGE_PLUGINS`; a group manager cannot set one. The
  share dialog has a **Group Access** section
  (`web/src/sections/modals/skills/SkillGroupAccess.tsx`) for those holders:
  one row per group with its setting. The dialog keeps one list of group
  settings; each row's share comes from the share draft
  (`web/src/lib/skills/sharing.ts:groupAccessRows`), and Save sends the
  changed settings. `PluginAccess.group_shares` is derived from `group_rows`.
  Only organization-wide
  `MANAGE_PLUGINS` deletes a skill that is required for anyone
  (`db/plugin_access.py:plugin_required_for_anyone`: a REQUIRED company setting,
  or a REQUIRED group setting for a group member who can see the plugin). The
  delete route and `SkillResponse.can_delete` share one rule
  (`db/skill.py:may_delete_skill`); the UI shows Delete from `can_delete`.
  `required_for_user` (the setting for the caller is REQUIRED, from the company
  or a group) shows the Required badge.
- **Admin skill policies** on Admin Panel → Skills, which shows whether
  or not Craft is on: Skill
  Publishing ([[#publishing-review]]), **Default Access** (the Organization
  library default for published skills with no own setting: Available,
  Installed by default or Not available; never Required) and **Sharing** (off:
  only organization-wide managers add user or group shares).
- **Bulk management.** **Admin Panel → Skills** and **Admin Panel → Plugins**
  ([[plugins]]) support selection of custom skills (`lib/skills/hooks.ts:useSkillBulkSelection`, UI in `sections/skills/useSkillBulkActions.tsx`), bulk access and installation changes,
  personal enable/disable, and confirmed deletion. Admins see all manageable
  custom skills. Bulk sharing adds or updates supplied individual grants;
  omitted visibility and installation settings remain unchanged. Failed items
  stay selected. Admin Skills filters by exact group. Admin Plugins filters by
  status, and its search also matches group names. Search and filter changes
  clear selection. The bulk Share dialog loads users and groups only while it
  is open.
  `SkillResponse.group_summaries` lists the `plugin__user_group` rows (group,
  permission or none, setting) to a caller who may edit the skill, and to a
  scoped manager only the rows of their groups. The admin table shows them in
  the Audience column, and the list has a group filter built from them.
  The Audience column shows the install setting of a published skill, else
  "Only the owner" or "Shared with people or groups" from `public_permission`
  and the server's `is_personal`; share-detail arrays can be hidden, so empty
  arrays do not mean a skill is personal.
- **Skill limit notices.** A refused write of the user's own (413
  `SKILL_LIMIT_EXCEEDED`) shows the limit where the user made the change
  (`web/src/lib/skills/hooks.ts:useSkillLimitCopy`). Bulk and import rows
  show the server's text. When `skill_omissions` (on the session read, the
  reload and the 30 s `sandbox-status` poll, so a push by someone else
  arrives) lists skills the run-time rule left out, `SkillRuntimeNotice`
  (`web/src/app/craft/components/`) shows a card above the composer with
  their names, **Manage skills** and **Dismiss**. Dismiss hides that list
  only. It waits while the session is stale. The admin Skills page shows
  `SkillLimitUsersBanner` (`web/src/sections/skills/`) when
  `GET /skills/users-over-limit` lists users: the first 10, then a count.
- **Skill page.** A custom skill opens at `/app/customize/skills/[id]`
  (`sections/customize/CustomizeSkillPage.tsx`): a header with the owner, the
  current and published versions, Copy link, Share, a menu (Edit, Remove) and
  the switch, or Add for a published skill the user has not turned on; tabs
  Overview, Contents and Versions (owners and editors only). Contents
  (`web/src/sections/customize/SkillContentsTab.tsx`) shows the files beside a viewer; Edit, or `?edit=1`,
  edits SKILL.md as text (frontmatter `name` and `description`, then the
  instructions) and stages added and removed files. Save Version sends a PATCH,
  then each upload, then each removal, each with the version the step before
  made as `base_version_id`, so one save can make several versions. The first
  base is the version the edit started from, so a newer save by someone else
  is refused (stale notice with Reload). A finished step leaves the staged
  list, so Save retries only the rest. There is no file
  content endpoint, so only SKILL.md shows text. `SkillEditorPage` only
  creates a skill (`/app/customize/skills/new`), in the same files-and-SKILL.md
  card (`web/src/sections/customize/SkillBundleEditor.tsx`). Create merges every
  added upload, without the removed files, into one ZIP
  (`lib/skills/bundleUpload.ts:mergeSkillFilesUploads`) and sends it with the
  sharing in one `POST /skills/custom/editor`, so the first version holds
  every file. A SKILL.md bundle replaces the text and
  the files after a confirmation.
  The skill comes from `GET /skills`; only owners and editors read
  `/skills/custom/{id}/edit` (it is 404 for a viewer), and a viewer reads the
  instructions and the supporting file list from `/skills/{id}/preview`. `ShareSkillModal` holds only the
  share settings. Admin Panel → Skills (`views/SkillsPage.tsx`,
  `sections/skills/AdminSkillsTable.tsx`; `kind: plugin` rows are on Admin
  Panel → Plugins) is an inventory table (Name, Source,
  Version, Audience with the group names, switch, row menu with Share and
  Delete) above which the bulk toolbar and a publish request banner stay (its
  Review opens the requests in a dialog, and a request's Review swaps it for
  the review dialog); a row opens
  the same skill page at `/admin/skills/[id]` with a back link to the
  inventory. The skill, integration and plugin pages share
  `sections/customize/CustomizeDetailLayout.tsx` (back link, header, underline
  tabs, and `DetailOverview`: the description beside a card of `KeyValue`
  facts). Built-in skills keep a preview-only dialog.
- **Access at import.** Multiple-ZIP upload accepts one set
  of sharing settings for the selection. The single-skill editor accepts
  sharing before creation. These use the same sharing checks as later edits.
- **In chat**, the agent sees the names and descriptions of the user's
  enabled custom skills and, when the turn has the sandbox tools, the
  available chat built-ins (`skills/built_in.py:CHAT_BUILT_IN_SKILL_IDS`:
  pptx; chats browse with the browser tools, not the browser skill). In this catalog, a skill's
  `metadata.short-description` replaces its description when it has one;
  `skills_list` shows the full description. The agent reads a skill's
  SKILL.md with its skill read tool (`skills_read`, or `skill` for Claude
  models) when the task matches. Deep Research and its
  research agents get the same catalog and both tools.
  A skill the user mentions in a message adds its SKILL.md, frontmatter
  included, right after the message, as it was read when the message was
  accepted, at the version the user ran. A SKILL.md over 8,000 bytes is cut
  there, with a note that gives the character to continue reading from; it
  names no tool, so a model of either tool family reads it. History keeps that text, so a later edit, a deletion or lost access
  does not change what earlier turns see. A skill that cannot be read when
  the message is accepted is not applied. In a turn with the sandbox tools,
  the SKILL.md (from `skills_read` or a pick) of a skill with other files
  starts with a `Skill files: /var/lib/onyx/skills/<name>/ (read-only)` line that tells
  the model to call `load_skill` first (`skills/content.py:read_chat_skills_md`;
  a custom version with no `file_manifest` keeps the line).
  `load_skill` copies the skill's files, built-in or custom, at the version
  the user runs then, into that folder; reads and picks copy nothing. The
  folder is shared by the user's chats on the VM, one copy per skill; a new
  version replaces it. To change a file, the agent copies the skill into its
  working directory. Without the sandbox tools, chat cannot open a custom
  skill's other files. App built-ins, company-search,
  image-generation and craft-documentation stay out of chat.
  A built-in is a built-in plugin in code (`BuiltInSkillDefinition.skills`):
  one skill with SKILL.md at its root, or one skill per
  `skills/<name>/SKILL.md`, as in an uploaded plugin version. Each skill of a
  built-in plugin is one chat skill, and the push puts each skill in its own
  folder. Built-ins have no plugin rows; their `ChatSkill.version_id` is the
  `skill` row id, with `built_in_skill_id` set.
  In the chat input, `@` at the start of a word opens a picker of these
  skills, with a **Manage skills** row that opens Customize → Skills (`lib/skills/hooks.ts:useChatSkills`, from `GET /api/skills/chat`),
  filtered by name prefix without case. In an incognito, multi-model or
  Deep Research chat the picker leaves built-ins out (`useChatSkills({ builtIns })`).
  A row shows the skill's short
  description when it has one, else its description. A skill change in the
  library, the skill editor, a plugin's Skills tab or a Craft app connection
  fetches the list again (`lib/skills/cache.ts:refreshSkillLists`). Other
  changes, such as one from another tab or user, show after the chat input,
  the Craft input or a scheduled task prompt gains focus, unless a fetch of the list started in the last minute; a
  window focus does not fetch the list. A message mentions at most 20 skills: at that
  limit, the picker offers only the skills already picked, and each request
  sends only the first 20 (`lib/chat/mentions.ts:requestMentions`). The query
  is the whole word, from the `@` through the caret to the next whitespace.
  Only typing or deleting opens the picker or changes its query. A paste, a
  drop and any other caret move, such as a click or an arrow key, close it,
  and a word that matches no skill closes it. Esc hides it until the user deletes the
  `@`. A pick replaces the whole word with a mention tile that reads `@name`.
  Craft's `/` pickers, in the input bar and in the scheduled task prompt,
  follow the same rules and match a substring
  (`lib/skills/hooks.ts:useEntryPicker`). They offer the built-ins from
  `GET /skills` and the custom skills from `GET /skills/chat`, one per skill of
  a plugin by its own name (`lib/skills/picker.ts:toPickerSections`). The tiles are the mentions: only a pick
  mentions a skill, so typed or pasted `@name` text does not. Removing a tile
  by delete or cut removes its mention, and undo brings it back. A draft,
  a failed send's restore and voice input keep each tile where it was, also
  against other text such as `(` or a word typed after it, and leave typed
  `@name` text as text. Voice auto-send sends only the mentions whose
  `@name` is still in the sent text. A message with picks that the user sends while a
  response runs carries its mentions like any pending input: a send applies
  them in the running response when the response accepts the message, and a
  queued or interrupting message applies them in its own turn. While the picker is open, the `/` prompt shortcuts stay closed. In the owner's chat
  view, a sent question shows each skill it mentioned as a chip, first from
  the picks and then from the recorded mentions. A message accepted during a
  response shows the mentions of its `user_message` packet, live and after
  reload. A shared view of the chat
  gets no mentions, and Craft shows plain text.
- **In a running Craft session**, a skill change does not reach the agent at
  once. The session shows a stale-skills notice with a reload action. The
  reload restarts the agent's runtime with the current skills.

When it fails:
- A bundle with bad frontmatter, an unsafe path, a reserved name, or a
  `.template` file is rejected with a message. A direct upload over a size or
  file count limit is rejected with a 413 that names the limit. Batch uploads
  list the Skill in `not_imported`.
  A frontmatter field that Onyx does not read (`license`, `compatibility`,
  `metadata`, `allowed-tools`) with a value it cannot read is kept as written
  and does not block the skill. Messages name the field in plain words.
- Turning on a skill whose name another enabled skill the user can see uses
  returns a name conflict. The client can retry with `replace_conflict` to
  switch skills. The kept choice of a skill the user can no longer see neither
  blocks the switch nor changes.
- When two enabled skills still share a name, for example after a share or a
  publish, the sandbox gets one of them by the name order. The other shows as
  off. The push does not fail.
- A required skill rejects a toggle.
- If a push to a sandbox fails, the change still saves. The sandbox keeps its
  old skills until the next push, session start or reload.
- A reload while a turn runs is refused with a message to wait.

---

## Scope

This component owns the built-in skill rows; the plugin tables ([[#plugin-tables]]); bundle parsing and validation; built-in skill definitions;
per-user rendering of templates; GitHub marketplaces and their sync; the push of a user's skill
files into a sandbox; and the skills library UI.

Neighbours own the rest:
- [[craft-sandboxes]]: the sandbox, the managed volume and the push transport.
- [[craft-sessions]]: `BuildSession.skills_hash`, the stale check and the
  reload.
- [[craft-external-apps]]: app connection, action policy, and credential
  injection at call time. The sandbox proxy enforces policy, not the skill
  text.
- [[file-store-and-user-files]]: stores custom bundles as blobs.
- [[context-assembly]]: where the chat skills catalog and mentioned skills
  go in the prompt. [[tools-framework]]: how the chat skill tools run.

---

## Architecture

```
skill mutation (server/features/skill/api.py)   compute affected users BEFORE the change
  -> db write, commit
  -> push_skills_for_users       skills/push.py
       lock_sandbox_skills_states        SELECT ... FOR UPDATE on Sandbox rows
       per sandbox, in id order, built one at a time:
       build_user_skills_payload         -> UserSkillsPayload (files, omissions)
         list_runtime_skills_for_user    db/skill.py: the one runtime gate, in keep
                                         order; each custom skill comes with the plugin
                                         version the user runs and its recorded size
         _assemble_skills                one fit loop: whole plugins within 900 MB and
                                         10,000 files; built-ins from disk, custom from
                                         the FileStore bundle of that version, in a
                                         folder named by its frontmatter (each
                                         skills/<name>/ of a plugin version in its own
                                         folder); resolves ${CLAUDE_SKILL_DIR}
         build_connectable_apps_list     guidance for unconnected apps
       compute_skill_runtime_hash        skip a sandbox whose hash matches
       push_to_sandboxes(SKILLS_MOUNT_PATH)   parallel batches of 10 sandboxes, or
                                         fewer when a batch reaches 256 MB of files
       set_sandbox_skills_states__no_commit   hash + skill_omissions, only for
                                         successful pushes (omissions also on a hash skip)
  -> commit
session start: sandbox_lifecycle.py:build_managed_content_payload
  uses the same payload and hash, before the sandbox is RUNNING
```

**One data model.** A custom skill is a plugin (`db/plugin.py`,
[[#plugin-tables]]) whose version holds one skill at the bundle root; the
skill id is the plugin id. An uploaded plugin's version holds its skills in
`skills/<name>/`, one `plugin_skill` row each, or no skill
([[#plugin-upload]]). `db/skill.py` passes the `Plugin` row for a custom
skill and the `Skill` row for a built-in (`StoredSkill`). Every read and write
of a custom skill uses the plugin rows: access, names, validity, bundles and
content. Built-in skills have no plugin. Old custom `skill` rows and the
tables `skill__user`, `skill__user_group` and `user_skill_preference` stay in
the database for a rollback, with no model; `alembic/env.py` keeps
autogenerate from dropping them. No code reads or writes them, except that a
skill delete also deletes the old row with the same id. Every query on
`Skill` filters `built_in_skill_id IS NOT NULL`. Lock order: the user's
preference lock, then plugin rows in id order.

**The runtime gate.** `db/skill.py:list_runtime_skills_for_user` decides what
a sandbox gets. It combines visibility, enablement
and the name order (`_user_skill_selection`), bundle validity
(`is_valid` of the version the user runs not false), the built-in app skills
the user gets ([[#built-in-app-skill-rule]]) and built-in availability
(`_built_in_skill_select`). Every user gets each available built-in. These inputs stay independent. A
required skill still needs a valid bundle. No input checks an app connection.

**Enablement.** `db/plugin_access.py:load_user_plugin_states` is the one rule
for API responses, toggles, the write limit, the runtime gate and the admin
list. One query gives, for many users and plugins, the install setting,
visibility, the version the user runs, its skill names, whether it can run
(enabled and a version that is not invalid), its recorded size, the keep key and the user's
choice under the setting: required is on, default is on until an opt-out,
available is on after an opt-in, a hidden plugin is off and its saved choice
stays. Built-ins are on.
`db/skill.py:_user_skill_selection` reads it for one user.

**Name order.** When two enabled skills of a user have one name,
`db/plugin_access.py:order_skill_names` keeps one: a built-in name, then a
plugin required for the user, then a published one, then the user's own,
then a shared one. The older plugin (`plugin.created_at`, then id) wins a
tie. It returns the one set of plugins that lose a name: they do not load and
show as off. Only skills that can run take part, and the names of the
built-in skills the user gets, and of their nested skills, are reserved. The toggle and the auto-enable
count a conflict by the same rule (`db/skill.py:_UserSkillSelection.other_skills_named`).

**Two hashes.** `compute_skill_runtime_hash` is a SHA-256 over every rendered
file path and its bytes, plus the connectable-apps text. `Sandbox.skills_hash`
records what was last pushed to the sandbox. `BuildSession.skills_hash`
records what the live runtime of a session loaded. A session is stale when the
two differ
(`db/build_session.py:session_runtime_stale`). A push
changes only the sandbox side. The runtime reads the skills directory once per
instance, so only a reload (`SessionManager.reload_session_skills`) or a new
session applies the change. The craft MCP set has its own `mcp_config_hash`
and triggers the same reload.

**Templates.** A built-in with a SKILL.md.template is rendered per user in
`skills/push.py:_render_template`. `company-search` lists the user's connected
sources. Built-in app skills fill app values, cloud-only blocks, and a list of
actions the admin denied (`skills/rendering.py:render_external_app_skill`), for
the app that the rule picks (`RuntimeSkill.external_app_id`). Custom skills are
never rendered.
**Chat.** `db/skill.py:list_chat_skills` is the one definition of the skills
chat gets: the custom skills the sandbox loads for the user
(`_UserSkillSelection.loaded`, the same selection as
`list_runtime_skills_for_user`: install settings, the user's choice, the name
order and a version that is not invalid), with the name, description,
`metadata.short-description` and id of the version the user runs. With
`with_sandbox`, it also lists `list_chat_built_in_skills`, the built-ins that
`load_skill` copies into the VM; they do not depend on the user. Anonymous users get none. `chat/process_message.py:prepare_chat_turn` reads it for the
turn's picks and reservation, each agent reads it once when it is built (for
its catalog), each skill tool call reads it, and so does each accepted
mid-run message with picks. The `@` picker reads it through
`server/features/skill/api.py:list_chat_skills_for_current_user`, which
returns `description` and `short_description`. `skills/models.py:ChatSkill`
makes each description one line (runs of whitespace become one space), and a
blank short description counts as none. Only the catalog and the picker
prefer the short description; `skills_list` shows the full one.
`skills/chat.py:render_skills_catalog` renders the catalog with Codex's
limits: 2% of the context window in tokens, where each line, newline
included, costs one token per 4 UTF-8 bytes, rounded up; 1,024 characters for
one description. If every line fits, descriptions are whole; else description
characters go to each skill in turn. Only the 1,024-character cut adds `...`;
a cut to fit the budget adds no ellipsis. If even the names do not fit, the
catalog keeps each name that still fits, in order, and ends with a line that
counts the omitted skills; if not even that line fits, there is no catalog. `tools/tool_implementations/skills/skill_tools.py:skills_catalog_message`
is the one builder of the catalog message for chat, Deep Research and
research agents. A pick is structured input,
as in Codex's mentions: a mention (`chat/mention_models.py`) is a
discriminated union on `type`, and a skill (`SkillMention`, `{type: "skill",
name}`) is its only kind. Later kinds, such as plugins and MCP servers, join
the union; the request rejects a kind it does not know. The client sends the
mentions in `SendMessageRequest.mentions`, or in
`PendingChatMessageRequest.mentions`, which `ChatInput.mentions` keeps for
the pending message. The server never parses message text. A message's
picks are accepted once, by `skills/chat.py:accept_picked_skills`, against a
skill list: it resolves each skill in that list and reads the SKILL.md of all
picks in one batched read with the user's current access
(`skills/content.py:read_versions_skill_md`). The read gives the whole
SKILL.md, frontmatter included, as Codex does. Each text over 8,000 bytes is
cut there, with a note that gives the character to continue reading from.
A skill that is not in the list or whose SKILL.md cannot be read is not
recorded. The result (`AcceptedPicks`) keeps two lists: the records
(`RecordedSkillMention`: type, name and version id) and, for each record,
the `<skill>` message it gives the model (`PickedSkillMessage`: version id,
content and the token count taken at acceptance).
`prepare_chat_turn` accepts a question's picks against the turn's list,
after the checks that can reject the question (the Deep Research and
incognito checks), and stores the records in `chat_message.mentions` and the
messages in the deferred column `chat_message.skill_messages`;
regeneration reuses them. Only `db/chat.py:load_message_branch`, the branch
load for model history, loads `skill_messages`. Chat loads for display,
shared views and exports do not. A row of a content-free session stores no
skill messages; temporary history holds them. A send into a running response
is accepted when the run accepts it
(`chat/run_store.py:ChatRunStore.receive_inputs`), against the user's
current chat skills, and its picks apply in that response. The accepted input (`ChatResponseItem.inputs`,
`AcceptedChatInput`) stores its `mentions` and `skill_messages`. Loading a
chat for display reads this column, so it parses the skill text of sends with
picks and drops it; that is accepted because such sends are rare. EE query
history returns its own type (`AcceptedInputSnapshot`) with the records only. API
fields and packets carry only the records, so no client gets the text. The
turn's ID packet and the message detail carry the records
(`ChatTurnSetup.mentions`), and the `user_message` packet of an accepted
send carries its records. A shared view empties both.
`AgentMessage` passes them to `HumanMessageBubble`, the chip path of a sent
question.
The composer (`sections/input/AppInputBar.tsx`) holds the mentions as
mention tiles in its input (`hooks/useContentEditable.ts`), so undo, cut and
code that replaces the text change them with the text. A send reads the text
and the tiles as one `lib/chat/types.ts:ComposedMessage`: one mention per
tile, each with `index`, where its `@name` starts in the text
(`lib/contentEditable.ts:readContent`). The server gets each mention once,
without `index`, and at most 20 of them
(`lib/chat/mentions.ts:requestMentions`). The draft, a failed
send's restore and voice transcription keep the indexes, so
`useContentEditable`'s `setMessage` puts each tile back at its index. Only
server data has no index: a withdrawn queued message, an edited question and
the chips of a sent question place each recorded mention on the first
`@name` of its skill that no other tile holds, longer names first
(`lib/chat/mentions.ts:placeMentions`). Older drafts, plain text or mentions
without an index, restore by that rule too. The `@` menu uses
the Craft picker's `PickerSections`: chat fills only `skills`, and a new kind
adds its section and maps its picker entry to a mention. The picker opens at
a word start (`lib/skills/picker.ts:detectPickerTrigger`), but a tile can sit
against any text. An edit sends the recorded mentions that its text still
has, and a resend or regeneration sends the recorded mentions. The agent preview passes its skill mentions to
the new chat in the `skills` URL parameter. Each stored skill message
becomes a user-role `<skill>` message right after the message that picked
it: `chat/chat_utils.py:convert_chat_history` for a question and
`chat/models.py:accepted_input_messages` for an accepted send
([[context-assembly]]). Old turns are never read again, so a deleted or
revoked skill keeps its text in old turns, as in Codex. The read
(`db/plugin.py:get_visible_versions_skill_md`) returns text only for versions
of skills the user can see at acceptance: the pinned version decides the
content, and current access decides whether it is read.
`chat/execution.py:construct_chat_tools` adds `skills_list` and the skill read
tool, `skills_read` or `skill` for Claude models
(`tools/tool_implementations/skills/skill_tools.py`) when the user has a chat
skill when the turn starts (`ChatTurnSetup.has_chat_skills`), whatever the
agent's tool selection; restored and child agents get them with the other
configured tools. The Deep Research orchestrator binds both in its research
phase, and its research agents bind both. The tools hold only the user: each
call reads the user's current chat skills (`list_chat_skills`), and
`skills_read` reads the SKILL.md, frontmatter included, of the version the
user runs now, with the same access check, in parts of up to 32,000
characters that a `start_char` offset continues. The catalog is a snapshot:
each agent loads the user's chat skills once, when it is built
(`tools/tool_implementations/skills/skill_tools.py:skills_catalog_message`), and renders it for its own
model's window, so the catalog stays the same across the agent's steps.

The library preview of a built-in app skill calls the same renderer, with
the app from the same rule
(`server/features/skill/response_helpers.py:skill_preview_response`). The
`company-search` preview shows the unrendered template.

---

## Contracts and traps

1. `rendering-input-changes-hash` **A new rendering input must change the
   hash.** If a value that changes the rendered files is not in the bytes that
   `skills/push.py:compute_skill_runtime_hash` reads, an edit never re-pushes and sessions
   never go stale. The hash covers the bytes of the version each user runs, so a
   change to `published_version_id` re-pushes to organization-only users.
2. `affected-users-before-change` **Compute affected users before the
   change.** `db/plugin_access.py:affected_user_ids_for_plugins` finds users with a running sandbox
   who can see the skill, by the plugin visibility rule in one query (it
   takes a set and reads `_user_plugin_pairs`). It ignores preferences on purpose, so that a delete
   or a disable still pushes to the users who had the skill. The delete route
   reads the audience before it deletes. The share, transfer and edit routes
   push to the union of the audience before and after. A new mutation must do
   the same, or a user who loses access keeps the files.
3. `shared-read-predicates` **Every new read path must use the shared
   predicates.** Reads use `db/skill.py:fetch_skill` and `list_skills`
   (`_visible_custom_skill_select`). Edits use `db/skill.py:fetch_editable_skill`
   (`_editable_by_user`). A query on `Plugin` without them skips sharing. The
   reads list every plugin; `SkillResponse.kind` is `plugin` when the version
   the user runs is not a skill (`db/plugin_access.py:holds_one_root_skill`).
   An edit of the files finds only a skill; the access routes (share,
   publish, review, versions, delete, bulk) pass `any_plugin=True`. Both read
   the plugin tables through `db/plugin_access.py`: visibility and the install
   setting come only from `db/plugin_access.py:_user_plugin_pairs` (through
   `visible_plugin_ids`, `load_user_plugin_states` and
   `affected_user_ids_for_plugins`); edits use `plugin_editable_by_user`. There is no organization-wide edit. A `plugin__user_group`
   row with no permission holds only a group install setting and grants
   nothing. Only such a row can be `NOT_AVAILABLE`: a row with a share and
   `NOT_AVAILABLE` is refused (400, "Remove the group's share first"). The
   author and a direct share get at least available, also past a group
   `NOT_AVAILABLE`. Built-in skills have no plugin and keep their skill
   rows. A scoped manager edits a private skill only when every group share is
   in their groups and every user share goes to a member of those groups. One
   SQL predicate, `db/plugin_access.py:plugin_in_managed_scope`, decides it for
   the edit check and the response permission.
4. `enablement-not-preference-row` **Never infer enablement from a preference
   row.** Use `db/plugin_access.py:load_user_plugin_states`. It reads
   `user_plugin_preference` and the install setting that applies to the user
   (the plugin's setting or
   its marketplace default, the most open non-default group setting, and at
   least available for the author or with a share). Disable writes `enabled=False`; it does
   not delete the row. A required policy overrides an opt-out without deleting
   it, so the opt-out returns when the policy goes back to default.
5. `name-uniqueness-in-db` **Only plugin.name is unique, per marketplace.**
   `uq_plugin_marketplace_name`: a new plugin with a used name takes the next
   free name (`db/plugin.py:free_plugin_name`); a concurrent create that takes
   it first fails and the user tries again. Publish and transfer
   refuse a clash with `CONFLICT`. Skill names repeat across plugins; never
   compare one with `plugin.name`. Two skills with one name can both be
   Default or Required; the run-time name order picks one. A toggle conflicts only with skills the user can see. Every write that
   enables a preference first takes `db/skill_limit.py:lock_user_skill_preferences`,
   a `FOR NO KEY UPDATE` lock on the user row. The lock orders concurrent
   enables of one name, so the second one gets `SKILL_NAME_CONFLICT`. The
   lock does not block the `FOR KEY SHARE` locks that foreign-key checks take,
   so sharing writes that reference the user still run. A new preference
   writer, such as an auto-enable, must take the same lock.
   The run-time name order (Architecture, Name order) keeps one skill for each name,
   because the name is the sandbox directory, so a duplicate never fails a
   push. For a custom skill that name is
   `frontmatter->>'name'` of the version the user runs.
6. `name-immutable` **A skill name never changes.** The frontmatter `name`,
   `Skill.name` and the bundle's wrapper directory, when there is one, must
   match (`skills/metadata.py:parse_skill_document`). Storage removes the
   wrapper. A rename is a delete and a new skill. Custom names cannot match a
   built-in.
7. `validate-before-sandbox` **Validate before content reaches a sandbox.**
   `_assemble_fileset` unzips the bundle of the version a user runs only when
   that version's `is_valid` is true, or after
   `skills/validation.py:validate_stored_custom_skill` passes for an
   unclassified version (it checks the name in the version's frontmatter).
   `db/skill.py:persist_skill_validity` writes the result to the plugin
   versions that hold that bundle and are still unclassified.
   Writes check four limits in `skills/bundle.py:normalize_custom_bundle`.
   Count all non-directory archive entries, including ignored files. Check
   both the incoming and normalized ZIP sizes. Raw uploads use the per-file
   read cap; ZIP uploads use the ZIP cap.
   Stored-bundle reads follow `bundle-size-limits`.
8. `templates-built-in-only` **Only built-ins use templates.**
   `skills/bundle.py:normalize_custom_bundle` and
   `skills/bundle.py:update_custom_bundle_files` reject `.template` files. If
   you convert a built-in's SKILL.md into a template, add its renderer branch
   in `skills/push.py:_render_template` in the same change. The
   static copy skips template sources, and a templated built-in with no
   renderer only logs a warning, so the skill ships no SKILL.md.
9. `unresolved-marker-fails` **An unresolved `{{` marker fails the render.**
   `skills/rendering.py:render_external_app_skill` raises rather than send broken instructions.
   Other `.template` files in a built-in app skill get only `{{APP:...}}` values and no
   such check.
10. `built-in-app-skill-rule` **One rule decides who gets a built-in app
    skill.** `db/app_skill.py:built_in_app_skills` gives a user the
    built-in skill of a preset when an integration whose `external_app` row
    has an `app_type` in `skills/built_in.py:EXTERNAL_APP_BUILT_IN_SKILL_IDS`
    is on for the user (`on` in
    `db/integration_access.py:load_user_integration_states`: the user has
    access, the user's choice under the install setting is on, and
    `integration.enabled` is true). No plugin takes part in the rule.
    `external_app.enabled` is an old copy and is not read. The app of that integration renders the skill
    (`db/skill.py:RuntimeSkill`, `external_app_id`). The runtime list, the
    reserved chat names, `db/skill.py:skill_user_states` (on only for a user
    who gets it, never toggled), `db/skill.py:fetch_skill` (VIEW), the Skills
    list (`skills_list_response_for_user` drops a built-in that is not on) and
    the preview read it. Do not add a second check, and do not
    check the app connection. Nothing links a skill to an app: the
    `external_app__skill` table has no model and stays only for rollback.
    A custom skill written for an app is an ordinary plugin: it
    keeps its owner and shares, loads, counts for the limits and reaches chat.
    `db/external_app.py:associate_built_in_skill__no_commit` makes or reuses
    the built-in `Skill` row and refuses a second app of one built-in type.
11. `push-holds-row-locks` **The push holds row locks during network I/O.**
    `skills/push.py:push_skills_for_users` locks the target `Sandbox` rows, then builds
    and sends them in parallel batches while the transaction is open. The hash write is a savepoint,
    and the caller commits. The push catches and logs every exception, so a
    failed push never fails the API call. The next push repairs it, because
    the hash of a failed sandbox is not written.
12. `sharing-single-entry` **Every share, publish and install setting change
    goes through `db/plugin.py:apply_plugin_access_change__no_commit`.** It
    takes a set of plugin ids, a `PluginAccessChange` (user and group grants,
    group settings with no share change (`PluginGroupSetting`: creates a
    setting-only row; None removes the setting and deletes a row with no
    permission), `publish`, a three-state company install setting, and a mode:
    replace or add-only) and the actor. A skill has no access of its own: the skills API
    passes the plugin with the skill's id. The function locks the plugins in
    id order; checks the rules once for the set;
    writes each plugin in a savepoint, so one failure rolls
    back that plugin only; and reads the affected users for the whole set
    before and after. The routes then commit and push once. The skills layer
    calls it through `db/skill.py:share_skill__no_commit` (share route, editor
    create, patch visibility, imports with access settings) and
    `db/skill.py:bulk_share_skills__no_commit` (bulk, add-only shares, no
    group settings).
    `db/skill.py:replace_skill_shares`, `set_skill_installation_policy`,
    `set_skill_public_permission` and `transfer_skill_ownership` are thin
    callers with no actor, so they skip the permission checks. Do not write
    `plugin__user` or `plugin__user_group` anywhere else.
    Rules: a company install setting needs organization-wide `MANAGE_PLUGINS`
    (`has_global_permission`; never `has_permission`, which accepts a scoped
    grant). In `SkillShareRequest`, a missing `installation_policy` changes
    nothing, null means the marketplace default, and a value (AVAILABLE too)
    is the skill's own setting. A group
    keeps its install setting when the change does not set one, also when its
    share is removed (the row stays with no permission). Group settings come
    only from `group_settings` and need global `MANAGE_PLUGINS` (else 403); a
    group manager cannot set one. A group row with a share cannot be
    `NOT_AVAILABLE`. With `Settings.plugin_sharing`
    off, only global `MANAGE_PLUGINS` adds a share or changes its level
    (`db/plugin.py:check_sharing_allowed`); removing one stays allowed. A
    transfer keeps the old owner as an editor, so it is refused too
    (`server/features/skill/api.py:transfer_current_user_skill_ownership`). A
    group membership change (group API, SCIM) pushes to the users who joined
    or left in the background (`skills/push.py:enqueue_skill_push`, task
    `push_skills_to_users` on the `sandbox` queue), so a large sync does not
    wait for the pushes. Other routes push in the request, after their commit
    (`skills/push.py:push_skills_and_commit`). A marketplace default (the
    Organization library or a company GitHub marketplace) is written by
    `db/plugin.py:set_marketplace_default__no_commit`, which refuses
    `REQUIRED` only for the Organization library (a company marketplace can be
    Required, as in Claude) and returns the users of the plugins that follow
    it. A Required plugin keeps its skill names first; the plugin that loses
    one shows `name_held_by` (see the name order above). EDIT on a skill is not enough
    to change its groups: any
    change to the group set or levels is a `MANAGE_PLUGINS` action within scope
    (`auth/scoped_permissions.py:assert_within_scope`, [[authorization]]).
    Without it, an owner could push a skill into any group manager's scope.
    It compares against the stored plugin group shares (rows with a
    permission), and the privacy check uses the stored visibility and the
    request, so a public-to-private change in the same request cannot get past
    it. Publishing needs the author or global `MANAGE_PLUGINS`
    (`db/skill.py:ensure_can_edit_org_visibility`; the patch route calls it
    too). `db/skill.py:_publish_requested` checks every request for
    organization access: it refuses organization `EDITOR` and a change from
    published to private, for every route, bulk included. The admin
    Publishing setting then decides what a publish does
    ([[#publishing-review]]). A publish moves the
    plugin to the Organization library (`db/plugin.py:publish_plugin__no_commit`);
    a name clash there returns `CONFLICT`. Only global `MANAGE_PLUGINS` deletes
    a published or a required skill
    (`db/skill.py:delete_skill_for_user__no_commit`); the card, bulk menu and
    editor hide Delete to match. A transfer moves a private plugin to the new
    owner's "My uploads", and a name clash there returns `CONFLICT`. A
    private custom skill must have an owner: `ck_private_skill_has_owner`
    rejects a private skill with no author, so transfer or delete private
    skills before their owner is removed.
    Agents apply a looser form of the rule
    ([[agents-personas#group-share-needs-manage-agents]]).
    `POST /skills/bulk` sharing applies one change to every skill the user
    can edit, reports refusals and failures per skill, and pushes the combined
    affected audience once after commit. A refusal for the whole set, such as
    a scope or install setting refusal, fails every skill. Bulk delete applies
    each item in a savepoint. Bulk enable and disable change only the caller's preference.
    `POST /skills/custom/batch` and GitHub import create each bundle through
    `db/skill.py:create_skill_from_bundle__no_commit`, one savepoint per skill,
    so a bad bundle or a name conflict under a DEFAULT or REQUIRED policy lands
    in `not_imported` and the other skills still import.
13. `pptx-scripts-serve-previews` **The `pptx` skill's preview scripts also
    render Craft output previews.**
    `server/features/build/sandbox/base.py:document_preview_command` runs
    `skills/builtin/pptx/scripts/preview.py` and its LibreOffice helper,
    mounted under a versioned path apart from the managed skills. A change to
    those scripts changes PDF and PowerPoint thumbnails in the output panel
    ([[craft-sandboxes]]).
14. `built-in-removal-needs-migration` **Removing a built-in needs a
    migration that deletes its rows.** `_assemble_fileset` skips, with a
    warning, a `skill` row whose `built_in_skill_id` is not in
    `skills/built_in.py:_REGISTRY`, so the rows otherwise stay.
15. `skill-dir-placeholder` **Skill paths resolve to the sandbox folder.**
    `skills/push.py:_resolve_skill_dir` replaces each `${CLAUDE_SKILL_DIR}` in
    a skill's root SKILL.md with `<root>/<name>`: `/workspace/managed/skills`
    for Craft, `/var/lib/onyx/skills` (`CHAT_SKILLS_PATH`) for a chat VM copy. In a turn
    with the sandbox tools, `skills/content.py:read_chat_skills_md` resolves
    it to the same chat folder in the text the model reads. Only the
    sent bytes change. The stored bundle, its SHA-256 and other files keep the
    placeholder. A resolved SKILL.md over the per-file limit skips that whole
    Skill with a warning. The resolved bytes count in the run-time total
    ([[#runtime-skill-limit]]). Files without placeholders keep their previous
    delivery behavior.
    The sent bytes feed the runtime hash. OpenCode adds the base
    folder line and the relative-path rule itself, so the push adds neither.
    `backend/tests/unit/onyx/skills/test_skill_dir.py` fails when the sandbox
    `OPENCODE_VERSION` pin changes, so the next pin bump checks that OpenCode
    still does this.
17. `bundle-size-limits` **Upload limits do not apply to saved bundles.**
    `skills/bundle.py` limits are constants, not env vars: 25 MiB per file and
    100 MiB expanded for every bundle, plus a 25 MiB ZIP and 500 files for new
    uploads. Stored reads
    (`skills/validation.py:read_stored_bundle_bytes`) stop at
    `STORED_ZIP_MAX_BYTES` (the expanded-total limit), and an edit that would
    save a larger ZIP is refused, so every saved bundle loads again. They skip
    the ZIP-size
    and file-count limits. `skills/validation.py:validate_stored_custom_skill`
    returns `is_valid=None` for `PAYLOAD_TOO_LARGE`, so the push skips the Skill
    without saving it invalid. Edits that cannot add files (a SKILL.md rewrite, a
    file removal) and the editor's re-ingest use
    `skills/bundle.py:normalize_stored_bundle`, so a saved bundle over the ZIP-size
    or file-count limit stays editable. Merges that add files keep the upload
    limits, so repeated merges cannot pass them. A full-replacement upload in the
    editor does not read the current bundle. One limit applies to every new
    version, edits included: `skills/bundle.py:check_skill_md_size` refuses a
    SKILL.md over `SKILL_MD_MAX_BYTES` (256 KiB) or with a NUL character
    (400), because each version stores the text in a Postgres text column.
    `skills/ingest.py:ingest_skill_bundle` and the GitHub preview call
    it. Only direct uploads return 413. Batch uploads report
    `not_imported` and GitHub previews mark the Skill unavailable.
18. `bundle-file-list-memory` **ZIP metadata memory has a fixed bound.**
    Every Skill ZIP opens through `skills/bundle.py:open_bundle_zip`, which uses
    `file_processing/zip_limits.py:open_zip_within_directory_limit`. `zipfile`
    keeps one `ZipInfo` (about 550 bytes) for each file-list record, so a small
    ZIP with many empty entries can use hundreds of MiB. The opener limits the
    bytes `zipfile` reads while it opens: 1 MiB of file list for uploads
    (`ZIP_DIRECTORY_MAX_BYTES`) and 4 MiB for saved bundles
    (`STORED_ZIP_DIRECTORY_MAX_BYTES`). Over the limit is a 413
    `zip_metadata_bytes`. `normalize_custom_bundle` finds duplicate and
    file-versus-folder paths by sorting the paths, not by building every parent
    path. The push checks a Skill's recorded size, or its zip directory, against
    the transport cap (`skills/limits.py:SKILL_RUNTIME_MAX_BYTES`, 900 MiB)
    before it reads the files ([[#runtime-skill-limit]]).
19. `plugin-tables` **A custom skill lives only in the plugin tables.**
    Migration `cdec9dd9ca3d` adds `plugin_marketplace`,
    `plugin`, `plugin_version`, `plugin_skill`, `plugin__user`,
    `plugin__user_group` and `user_plugin_preference` (`db/models.py:Plugin`
    and its neighbours), and fills them from each custom skill. Built-in
    skills get no plugin. A backfilled plugin has the id of its old skill
    row; a skill made later has no skill row. A plugin exists only for
    skills: an integration stands alone and has no plugin
    ([[mcp-and-custom-tools#access-grants-default-chat-only]]). A publish or
    a transfer to a marketplace that has the plugin name is refused, or
    takes a free name on request (`db/plugin.py:_move_plugin__no_commit`).
    No foreign key checks the
    version pointers (`current_version_id`, `published_version_id`,
    `pending_version_id`); write them only through `db/plugin.py`, which sets
    them to a version of the same plugin.
    Public and author-less skills go to the Organization library, published.
    Other skills go to the author's "My uploads". A duplicate name in one
    marketplace gets the first free `-N` suffix on `plugin.name` only
    (`db/plugin.py:free_plugin_name` in app code). The skill name lives only
    in `plugin_skill.frontmatter` (NOT NULL, a check requires a string
    `name`); the backfill seeds it with the name and description of the
    old skill row. No column stores the kind (skill or plugin):
    `db/plugin.py:is_skill_version` reads it from the layout of each
    version. Every write and read of a custom skill uses the plugin rows
    ([[#bundle-change-adds-version]]); the skill responses read
    `db/plugin_access.py:load_plugin_access`. The list and
    runtime names and descriptions come from the frontmatter of the version
    the user runs. Migration `2d7510746863` adds `plugin_version.manifest`
    and `plugin_version.needs` (nullable JSONB, NULL for a skill version).
    An old custom skill row with no plugin is ignored. Migration
    `65f8d8cd1bf3` drops `ck_private_skill_has_owner`: old rows go stale, and
    the check would refuse a user delete. A user delete is refused
    while the user's "My uploads" holds a plugin
    (`db/plugin.py:private_plugins_blocking_user_delete`,
    `db/users.py:delete_user_from_db__no_commit`); the `CONFLICT` body lists
    them in `private_plugins`. Published plugins stay with no author. An
    integration of the user does not stop the delete: it loses its owner
    (`integration.owner_user_id`, ON DELETE SET NULL) and keeps its install
    setting and shares, so a private one stays private.
    `POST /manage/admin/transfer-private-plugins` (full admin) moves each
    of those plugins to one new owner in one transaction through
    `transfer_skill_ownership` with `on_name_clash="rename"`
    (`db/skill.py:transfer_private_plugins__no_commit`): a clash takes the
    next free plugin name, the response lists each rename, and shares stay.
    The admin user-delete dialog
    (`web/src/views/admin/UsersPage/UserActionModals.tsx:DeleteUserModal`)
    shows that list with a user picker, calls the transfer, then the delete. Migration `55bf66dd54dd` re-syncs every plugin from the
    skill rows once, before these reads, to fix rows that older code left
    stale; it copies `backfill_plugins_from_skills` instead of importing it.
    Reads of bundles,
    validity and content also come from the version: the runtime list, the
    push, session start and the hash take the version each user runs
    (`db/plugin_access.py:version_user_runs`). The editor and the edits read
    the current version. The preview and `is_valid` in responses read the
    version the user runs.
    Content of a version comes from one function,
    `skills/content.py:read_version_contents`: `plugin_version.file_manifest`
    and `plugin_skill.skill_md` from the database, and the bundle only when
    they are NULL (a version copied from an old skill row).
20. `bundle-change-adds-version` **A file change adds a plugin version and
    keeps the old bundle.** Each create and each change to a custom skill's
    files goes through `db/skill.py:create_custom_skill__no_commit` or
    `db/skill.py:replace_skill_bundle`, which call `db/plugin.py`. In one
    transaction they take the user lock, then the plugin row, add the next
    `plugin_version` with its file list (`skills/bundle.py:compute_bundle_manifest`)
    and `plugin_skill` row, and move `current_version_id`. A save never moves
    `published_version_id`: on a published skill the organization keeps the
    published version until a publish update ([[#publishing-review]]). An editor save
    whose file list equals the current version's adds no version, and the
    route deletes the new blob. A version copied from an old skill row has no
    file list, so editor routes pass `previous_manifest`, the list of the
    stored bundle; the bytes of a rewritten ZIP differ even when its files
    do not. A bundle upload always adds one. An edit
    request may carry `base_version_id`; if it is not the current version,
    the edit gets 409 `PLUGIN_VERSION_STALE`. Skill responses return the plugin's
    `current_version_id`, read with the name and description; the editor
    returns the id of the version whose content it read, so the editor's base
    always matches its fields. An editor write (the PATCH, a file upload or
    removal) returns the version it made, or its base when nothing changed,
    not a later read: a save by someone else in between would otherwise
    become the base of the next chained write and skip its stale check. Routes no longer delete the
    previous bundle, because older versions still point at it
    ([[#bundle-retention]]). Each new version stores `plugin_skill.skill_md`
    ([[#bundle-size-limits]]). `skills/metadata.py:frontmatter_for_jsonb`
    drops a frontmatter value that JSONB cannot hold and keeps every other
    key; name and description are always the validated strings.
21. `bundle-retention` **Every version keeps its bundle while the skill exists.**
    Routes never delete a bundle on save, because the version still points at
    it. A skill delete, single or bulk, returns every version bundle and the
    route deletes them after the commit
    (`file_store/staging.py:delete_files_best_effort`).
22. `version-history-api` **Version history uses the EDIT policy.** The
    owner, editors and global `MANAGE_PLUGINS` list every version
    (`GET /skills/custom/{id}/versions`), preview one
    (`GET .../versions/{version_id}`) and restore one
    (`POST .../versions/{version_id}/restore`); a viewer or a version of
    another skill gets 404. `review_status` is derived from the plugin
    pointers: `published`, `pending` or `draft`. Restore needs
    `base_version_id` (409 `PLUGIN_VERSION_STALE`) and saves through the
    editor save path, so equal files add no version. The list gives the
    plugin.json version (`manifest_version`) of a plugin version. UI:
    `web/src/sections/modals/skills/SkillVersionsTab.tsx`; a plugin version
    preview shows its skills and needs.
23. `publishing-review` **The Publishing setting governs every publish by
    authors.** Only the author or global `MANAGE_PLUGINS` publishes
    (`db/skill.py:ensure_can_edit_org_visibility`); an editor saves versions
    only. `db/plugin.py:publish_or_request_review__no_commit` is the one place
    `Settings.plugin_publishing` (`OPEN`, `REQUIRES_REVIEW`, `OFF`) applies; a
    failed settings read stops the publish. Global `MANAGE_PLUGINS` and a
    system write (`actor` None: community downgrade, approve) always
    publish. Every publish path calls it: the access-change
    write path for a private plugin, `POST /skills/custom/{id}/publish` and
    approve. A save never moves `published_version_id`. Review state is two
    pointers on `plugin`: a request sets `pending_version_id` (a newer request
    replaces it), and a publish or a deny clears it. There is no denied state.
    A new skill created published takes the next free name on a clash
    (`on_name_clash="rename"`); other publishes return CONFLICT. Requests
    (`GET /skills/review-requests`, approve, deny) need global
    `MANAGE_PLUGINS`; the list shows the plugin author and the version's
    `created_at`, and the admin approves or denies from a view of the version
    preview. The web hook `usePublishAction` mirrors the setting for the
    share dialog and the Versions tab.
    The **Skill Publishing** card on Admin Panel → Skills
    (`web/src/sections/skills/SkillPublishingCard.tsx`) also
    holds **Default Access**, saved with
    `PUT /skills/organization-library/default-access`, and **Sharing**, saved
    as `plugin_sharing`.
24. `chat-skills-one-definition` **Chat's skills have one definition and
    mentions are records.** Change which skills chat gets only in
    `db/skill.py:list_chat_skills`; the turn, the tools and the `@` picker all
    read it, and the web client does not decide which skills chat gets (the
    composer only limits a message to 20 picks). It gives one skill for each
    `plugin_skill` row of each version the sandbox loads; a SKILL.md read is
    keyed by version id and folder (`db/plugin.py:SkillKey`). When a loaded
    plugin needs an integration that is not on for the user, the catalog
    names it in one line
    (`tools/tool_implementations/skills/skill_tools.py:skills_catalog_message`). A skill
    mention is accepted only once, when its message is accepted
    (`skills/chat.py:accept_picked_skills`), and stored as a record (type,
    name, version id) and a `<skill>` message with the cut SKILL.md and its
    token count (`chat_message.mentions` and the deferred
    `chat_message.skill_messages`, or the accepted input). Never parse message text for mentions, and do not resolve or read
    stored mentions again against the user's current skills, or old turns
    change their prompt and chips. API fields carry the record without the
    text. Load `skill_messages` only for model history
    (`db/chat.py:load_message_branch`). A content-free incognito row keeps the
    record and no skill message
    ([[chat-persistence#incognito-decision-per-field]]).
25. `plugin-upload` **An uploaded plugin never gives access to an
    integration.** `skills/plugin_bundle.py:read_plugin_bundle` reads the zip
    with the skill upload limits: `.claude-plugin/plugin.json`,
    `.codex-plugin/plugin.json` or `plugin.json`, at the root or in one
    folder; skills in `skills/<name>/SKILL.md`; MCP servers in `.mcp.json` or
    `mcpServers`. It refuses a plugin with no skill and no MCP server. A zip
    with only a SKILL.md stays a skill upload. A need stores the normalized
    URL (`utils/url.py:normalize_mcp_server_url`) and no integration id.
    Each viewer sees that URL, so a URL with a credential (user info or a
    query value such as `api_key`), a `${VAR}` or a bad scheme is dropped;
    `url_problem` keeps the reason (`mcp_server_url_problem`) for the UI.
    `integrations/plugin_needs.py:need_views` matches it at read time against
    the integrations of `integrations_for_needs`, so a private integration
    the user cannot see is `not_added`. `integrations_for_needs` adds the
    server URL of each no-access integration for the match only, so a
    group-limited integration is `no_access`; the member list never shows that
    URL. One match gives that integration's member state; two give
    `more_than_one`. The save
    (`server/features/skill/api.py:save_plugin_upload`) adds a version to a
    plugin with the same name that the user edits and that is not a skill:
    the user's uploads first, then another user's uploads shared as EDITOR,
    then the Organization library (`db/plugin.py:find_upload_target`);
    `save_as_new` makes a new plugin with the next free name. The save stores
    the bundle, then takes the user row lock and finds the target under it, so
    two uploads of one new name make one plugin with two versions. A new version
    keeps shares, publishing and user choices. An upload with the files of
    the current version adds no version and returns `unchanged`. A new plugin
    with a skill name that another plugin the user runs holds is saved off;
    the preview and the save name those plugins (`name_conflicts`). A plugin
    the user turned on that loses a skill name gets `name_held_by`, the
    plugins that hold it (`db/skill.py:skill_user_states`); a 409
    `SKILL_NAME_CONFLICT` on a turn-on has `conflict_names`.
    `GET /skills/{id}/plugin-skill?path=` returns one skill's SKILL.md
    instructions in the version the user runs. `GET /skills` marks each custom
    skill `member_visible`: false for one a global `MANAGE_PLUGINS` user sees
    only through that permission; the Customize lists leave those out. The description is the plugin.json description of the version
    the user runs (`db/plugin_access.py:load_plugin_access`), so a draft
    version does not show to the users who run the published one. Version
    preview and restore take a plugin version too: the preview adds `files`
    and `plugin` (manifest, skills, needs), and a restore adds a version from
    the old bundle (`db/skill.py:restore_plugin_version__no_commit`). Turning a
    plugin on (`PUT /skills/{id}/enabled`, bulk enable, a new upload, and a
    new version of a plugin the user has on) turns
    on each needed integration in `turn_on` with a connected status, through
    `integrations/plugin_needs.py:turn_on_needed_integrations__no_commit`, and
    reloads the user's Craft sessions when one changed. Bulk enable does this
    one time for all the enabled plugins. An integration that the user lost
    access to after the read is skipped, so the enable does not fail.
    The on/off switch and the name order stay per plugin: a plugin that
    loses any skill name does not load.
26. `write-skill-limit` **A user's own write never moves that user past 500
    MB or 5,000 files of skills.** Limits are `skills/limits.py` constants. A
    user's total is the recorded size (`plugin_version.unpacked_size_bytes`,
    `file_count`) of the version the user runs, for each plugin on for the user
    that can run (`db/plugin_access.py:skill_usage_by_user`), plus the built-ins
    (`skills/built_in.py:built_in_skills_usage`, read once on first use).
    `db/skill_limit.py:check_skill_limit` takes the user row lock (`lock_user_skill_preferences`), measures the user
    before and after the write, and refuses an under -> over move with 413
    `SKILL_LIMIT_EXCEEDED` (`skill_limit`: `usage`, `max_bytes`, `max_files`).
    It covers toggle on, auto-enable of an upload, create (with its own share
    or publish, which can turn the skill on for the author), upload, import
    and editor create, and bundle save, restore and replace. A bundle save
    ingests with no lock; `db/skill.py:replace_skill_bundle` then takes the
    user lock and the plugin row, the toggle's order. Admin changes
    (settings, shares, Default access, publish, approve, transfer), app connect
    and group membership are never checked: the run-time rule and the admin
    banner handle a user they put past the limit. A user already over is not
    refused.
27. `runtime-skill-limit` **A sandbox gets every plugin that fits in 900 MB
    and 10,000 files.** `skills/push.py:build_user_skills_payload` applies it,
    so session start (`build_managed_content_payload`) and the push both do.
    `list_runtime_skills_for_user` returns the skills in keep order: built-in,
    Required, turned on (also Installed by default turned on again), Installed
    by default; inside a group the most recent first, then id. One fit loop in
    `skills/push.py:_assemble_skills` keeps whole plugins in that order. A
    custom skill counts the larger of its recorded size and the bytes it sends
    after `${CLAUDE_SKILL_DIR}` resolution, so the same total keeps the
    transport cap (see [[craft-sandboxes]]). Left-out plugins (`SkillOmission`:
    id, name, bytes, files, reason) go to `sandbox.skill_omissions` together
    with `skills_hash`, so they describe the content on that disk.
    `SessionResponse.skill_omissions` carries them to the session UI.
    `GET /skills/users-over-limit` (`MANAGE_PLUGINS`,
    `db/skill_limit.py:users_past_write_limit`) lists active users past the
    write limit with their usage and the omission count of their sandbox. An
    SQL sum of enabled, not invalid plugins
    (`db/plugin_access.py:users_with_usage_past`) picks the candidates, and
    the per-user read then runs for those users only.
28. `github-marketplaces` **A GitHub marketplace sync writes one read or
    nothing.** A `plugin_marketplace` row of kind `github` keeps its
    `repository`, `folder` and `ref` ('' for none; one unique index for
    personal and one for company sources), its login user and its last sync.
    `skills/marketplace/provider.py:marketplace_config` reads them as a
    `GitHubMarketplaceConfig`. Skill responses add `marketplace` (id, name, kind,
    repository and `personal`) and `content_locked`. `skills/marketplace/reader.py:read_marketplace` reads
    `.claude-plugin/marketplace.json` (then `.agents/plugins/marketplace.json`)
    and builds one bundle per entry through
    `skills/plugin_bundle.py:read_plugin_bundle`: the folder's plugin.json
    over the entry fields, or the entry fields alone; an entry `skills` list
    takes only those folders and the MCP files that the entry names. A bad entry is blocked and the rest go on;
    `github`, `url` and `git-subdir` sources on github.com are fetched from
    their repository (20 per sync, one repository in memory at a time); other
    sources and hosts are not supported, with a reason that names the source
    kind or the host. `skills/ingest_from_github.py:read_repository_archive`
    records symbolic links, and only an entry whose folder holds one is
    blocked. `skills/marketplace/reader.py:BundleBudget` holds the
    skill and size limits for local and remote plugins together.
    `skills/marketplace/compare.py:plan_marketplace_sync` decides the writes.
    A synced plugin has the name of its entry, and the plan matches plugins
    to entries by that name (unique per marketplace); the plugin.json name
    does not name it. An entry gets a version only when its file list
    changed; every gone entry deletes its plugin; a blocked entry keeps its
    plugin. "Is synced" is the marketplace kind (`db/plugin.py:is_synced`).
    `skills/marketplace/sync.py:sync_marketplace` stores only the bundles to
    write, then `db/marketplace.py:apply_marketplace_sync__no_commit` compares
    again under the marketplace row lock and writes all in one transaction. A
    failed read or a GitHub error only sets `last_error`. A failure before the
    commit deletes the stored bundles. One sync runs at a time per
    marketplace (cache lock `marketplace_sync:{id}`); a sync that finds the
    lock held does nothing. `skills/marketplace/sync.py:marketplace_syncing`
    is true while `marketplace_sync_queued:{id}` (task expiry TTL; a failed
    send deletes it) or `marketplace_syncing:{id}` (lock TTL, 5 minutes) is
    set. The run deletes the running key only while it still holds the lock.
    A running sync extends the lock and the key between steps (read, each
    other repository, each staged bundle, apply) and stops after 30 minutes,
    so a killed worker frees the marketplace within 5 minutes.
    `request_marketplace_sync` does nothing while `marketplace_syncing` is
    true, and the web turns Sync now off then. A sync whose lock expired writes nothing. A folder URL
    (`.../tree/<ref>/<folder>`) and `github.com/owner/repo` fill the ref and
    the folder. A personal add of a source that a company marketplace has is
    refused with CONFLICT. A missing branch and a missing repository give
    their own `last_error`. Remote entries read at most `REMOTE_REPOSITORY_MAX_COUNT` (20) other
    repositories without a GitHub login and
    `REMOTE_REPOSITORY_MAX_COUNT_WITH_LOGIN` (200) with one
    (`skills/marketplace/provider.py`); entries past it are blocked with a
    `MarketplaceReasonCode`, and the web shows one note for them. A plugin
    with only commands, agents or hooks is not supported with
    `SKILLS_AND_MCP_ONLY`. The web translates `reason_code` and keeps
    `reason` as the fallback (`lib/marketplaces/hooks.ts:useMarketplaceCopy`).
    `utils/github.py:github_rate_limited` puts GitHub's reset time in the
    error (`reset_at`), and a 422 for a ref that names no commit counts as
    not found. The preview says when the caller or the company already has
    the source (`db/marketplace.py:source_added_for`). `GitHubMarketplaceConfig` lowercases owner and repo, so the
    unique indexes catch a duplicate that differs only in case. Every JSON
    read in `skills/marketplace/reader.py` turns a `RecursionError` into a
    blocked entry or a failed read. Replace login needs no GitHub
    connection: the new login reads a public repository without one. The Celery task
    `sync_marketplace` runs on the `sandbox` queue; Onyx Lite runs the sync
    in the API server after the response. Company plugins have no author and
    `published_version_id` follows each version;
    `db/plugin_access.py:seen_by_organization` makes the organization see
    them. A personal plugin belongs to the marketplace owner and starts off, as
    in Claude; the owner turns plugins on one at a time. `db/plugin.py:refuse_if_synced`
    refuses content edits, uploads, restores, publishing, ownership transfer
    and delete of a synced plugin with "Change this plugin in GitHub.". A
    company plugin's shares and install settings still change. A personal
    plugin takes no user or group share and no install setting
    (`db/skill.py:_check_skill_access_change`), and a global plugin manager
    does not see or edit another user's personal plugins
    (`db/skill.py:_not_others_personal_marketplace`). `db/skill.py:may_delete_skill` takes
    `synced`, so `SkillResponse.can_delete` is false for a synced plugin. A user delete removes the user's personal
    marketplaces and their plugins (`db/users.py:delete_user_from_db__no_commit`
    returns a `UserDeleteCleanup`; after the commit, `finish_user_delete`
    deletes their bundle files and pushes skills to the users who could see
    them).
    The routes are in
    `server/features/skill/marketplace_api.py`, under `/marketplaces`;
    they authorize before any GitHub call. The web client is
    `web/src/lib/marketplaces/` (`web/src/lib/marketplaces/hooks.ts` reads the list again every 3 s
    while a marketplace syncs, and refreshes the skill lists when a sync
    changes plugins).

---

## Decisions

- **Rendered files, not a manifest, go into the hash.** Any change in rendered
  output, such as a new app connection or a denied action, marks sessions
  stale with no list of inputs to maintain.
- **A stale notice, not an automatic reload.** Reload disposes the live
  runtime, so the user chooses when. It refuses while a turn runs.
- **A push can change files during a turn (R30).** "A new version applies at
  the next message" holds only for the harness. The OpenCode push swaps the
  `/workspace/managed/skills` link at once, so a turn that is running can read
  the new files of a Skill. The previous tree stays readable until the next
  push to that mount or for 60 seconds.
- **App lifecycle keeps skill settings.** Disconnecting an app deletes only
  the user's connection
  (`backend/onyx/server/features/integrations/api.py:delete_member_connection`).
  Deleting an app keeps the skills of its plugins with their settings and
  choices (`db/external_app.py:delete_external_app__no_commit`). It deletes
  the built-in skill row of the app's preset.

---

## Known issues

- **A marketplace sync checks a plugin's shape, not its content.** The sync
  enforces archive size and member limits, path safety, the bundle limits
  and frontmatter rules. Nothing
  inspects the instructions or bundled scripts. A harmful skill is contained
  only by the sandbox and its egress proxy ([[craft-sandboxes]],
  [[craft-external-apps]]).
- **App skills reflect only workspace DENY.** `skills/rendering.py` lists an
  action as unavailable when its workspace policy (stored override or catalog
  default) is DENY, or when cloud withholds it. Personal and task DENY choices
  are not listed, so the agent can try an action that the proxy then blocks
  ([[craft-external-apps]]).
- **Integration writes reload sandboxes after the commit.** The old
  external-app admin routes are gone; integration writes call
  `backend/onyx/integrations/service.py:reload_craft_sessions` after the
  commit. The reload is best-effort: `push_skills_for_users` logs and drops
  every failure ([[#push-holds-row-locks]]), so a sandbox can keep old files
  until its next push.
- **A new app gives its built-in skill to nobody.** Creating an external app
  does not create an integration, so
  [[#built-in-app-skill-rule]] finds no user for that app. Apps that existed
  at migration `730bce2814a0` got their integration from it.

---

## Dependencies

- [[craft-sandboxes]]: `push_to_sandbox` and the managed volume.
- [[craft-sessions]]: the stale check and the reload that apply a push to a
  live runtime.
- [[craft-external-apps]]: the app rows behind built-in app skills, the
  connectable-apps list and action policy views. A marketplace preview uses
  the caller's connection of the GitHub integration, and a sync uses the
  login user's (`integrations/github_auth.py:github_authorization_for`,
  through `resolve_call_credentials`).
- [[authorization]]: `MANAGE_PLUGINS` and the scoped-manager group check
  (`assert_within_scope`).
- [[file-store-and-user-files]]: bundle blobs.
- [[image-generation]]: the image skill is available only when image
  generation is configured.

---

## Recipes

- `add-built-in-skill` **Add a built-in skill.** Copy `pptx` for a static skill, or
  `image-generation` for one that depends on a service through
  `is_available`. List the current set with `ls backend/onyx/skills/builtin/`
  and the providers in `skills/built_in.py:_REGISTRY`. Import-time checks fail
  on a duplicate id, a duplicate app type, a missing source file, or
  frontmatter whose `name` does not match the directory. A seeded
  built-in needs a migration that creates its row. An app built-in gets its
  row when an admin connects the app ([[craft-external-apps]]).
- `add-templated-built-in` **Add a templated built-in.** Copy `company-search`: a SKILL.md.template
  plus a renderer branch in `_render_template`
  ([[#templates-built-in-only]]). Put every value the renderer reads into the
  rendered bytes ([[#rendering-input-changes-hash]]).
- `add-skill-mutation-route` **Add a skill mutation route.** Copy `share_current_user_skill` in
  `server/features/skill/api.py`: compute `affected_user_ids_for_plugins`
  before the change, apply it, compute it again, commit, then call
  `skills/push.py:push_skills_and_commit` with the union
  ([[#affected-users-before-change]]). Its second commit holds only the push
  state: a failure there rolls back and logs, so the route still returns the
  saved change. A plain `db_session.commit()` there makes a retry save twice.
- `investigate-skill-missing` **Investigate "my skill is not in the sandbox".** Check the inputs of
  `list_runtime_skills_for_user` one at a time for that user: visibility,
  `load_user_plugin_states` (setting and choice), the name order
  (`order_skill_names`: another skill may hold the name), `plugin_version.is_valid` of the
  version the user runs (`version_user_runs`), and built-in availability.
  For a built-in app skill, check `db/app_skill.py:built_in_app_skills`. Then compare `Sandbox.skills_hash` with
  `BuildSession.skills_hash`: equal means the runtime loaded the last push;
  different means the session waits for a reload. Search the API server log
  for `Skill push failed` for a failed push.
- `test-skill-setup` **Set up skills for a test.** Use the integration manager
  `backend/tests/integration/common_utils/managers/skill.py`. A real push
  needs the Kubernetes harness in `backend/tests/integration/tests/craft/k8s/`.

---

## Verification

- `backend/tests/unit/onyx/skills/` covers bundles, validation, rendering,
  the repository archive read and the marketplace reader and compare.
- `backend/tests/external_dependency_unit/craft/marketplace/` covers the
  marketplace sync, the task lock, the API, access and the content lock with
  a fake GitHub (`backend/tests/external_dependency_unit/craft/fake_github.py`).
- `backend/tests/external_dependency_unit/craft/` (the `test_skill*` files)
  covers visibility, the fileset, affected users, ownership and push faults.
  `backend/tests/external_dependency_unit/craft/test_skill_version_reads.py` covers the version each user runs (an
  organization-only user runs the published version, a share recipient the
  current one, also in the push), and that the editor, the preview and the
  list make no file store read for content stored in the database.
- `backend/tests/external_dependency_unit/db/test_plugin_tables_migration.py`
  covers the plugin backfill,
  `backend/tests/external_dependency_unit/db/test_plugin_resync_migration.py`
  the re-sync, and
  `backend/tests/external_dependency_unit/db/test_plugin_constraints.py` the
  database rules of the plugin tables.
- `backend/tests/unit/onyx/skills/test_plugin_bundle.py` covers the plugin
  zip reader and `backend/tests/unit/onyx/utils/test_mcp_server_url.py` the
  URL rule. `backend/tests/external_dependency_unit/craft/test_plugin_upload.py`
  covers the save target, multi-skill run time and chat, need states, turn
  on and the chat line.
- `backend/tests/integration/tests/skills/` covers the API, bulk actions,
  import sharing and plugin version writes
  (`backend/tests/integration/tests/skills/test_skill_plugin_versions.py`),
  deleting a skill deletes every version bundle
  (`backend/tests/integration/tests/skills/test_skill_bundle_delete.py`),
  the version list, preview and restore
  (`backend/tests/integration/tests/skills/test_skill_version_api.py`), and
  publish, review and the Publishing setting
  (`backend/tests/integration/tests/skills/test_skill_publish_review.py`).
  `backend/tests/integration/tests/craft/k8s/` covers a real
  push.
- By hand: edit a skill while a Craft session runs. The stale notice must
  appear, and after reload the agent must read the new text.
