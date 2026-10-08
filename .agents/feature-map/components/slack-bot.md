# Slack Bot

> Onyx answering questions inside Slack. A background process (Socket Mode, not
> HTTP) listens for Slack events, matches standard answers or runs a chat turn
> in-process, and posts the answer back into the thread.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** platform (bot surface)
**Edition:** CE core listener and regular-answer path. Standard answers are EE
(`backend/ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py`); CE falls back to a
no-op that never matches. Multi-tenant scaling (per-pod tenant acquisition, Redis
locks) applies to cloud only.
**Owns:**
`backend/onyx/onyxbot/slack/listener.py`, `handlers/handle_message.py`,
`handlers/handle_regular_answer.py`, `handlers/handle_standard_answers.py`,
`handlers/handle_buttons.py`, `blocks.py`, `config.py`, `constants.py`, `models.py`,
`utils.py`, `backend/ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py`,
`backend/onyx/db/slack_bot.py`, `backend/onyx/db/slack_channel_config.py`,
`backend/onyx/server/manage/slack_bot.py`, `backend/onyx/server/manage/validate_tokens.py`,
`web/src/app/admin/bots/`

---

## 1. What the user experiences

A Slack user asks a question in a channel the bot is configured for, either by
tagging `@OnyxBot`, sending a DM, or (if the channel is configured to respond to
every message) just posting. The bot reacts with an emoji while it thinks, then
replies in the thread with an answer, source citations, and feedback buttons
(thumbs up/down, "show everyone" for ephemeral answers, "continue in web UI").
If the message matches a configured standard answer, the bot posts that instead
and skips the LLM entirely.

An admin installs a Slack app once, at **Admin > Bots** (`/admin/bots`,
`web/src/app/admin/bots/page.tsx`), by pasting a bot token and an app token from a
Slack app the admin created in the Slack API console (`bots/new`,
`SlackBotCreationForm.tsx` -> `SlackTokensForm.tsx`). Onyx runs the connection over
Slack's **Socket Mode**, so no public webhook URL is needed.

Per Slack bot, the admin then configures one or more channels
(`bots/[bot-id]/channels/new`, `SlackChannelConfigCreationForm.tsx`): which agent
(persona) answers, which document sets restrict its search, whether it responds to
every message or only tags/DMs, whether replies are ephemeral, follow-up tags,
answer filters (question-mark-only, cite-or-stay-silent), and which standard-answer
categories to check first. `bots/[bot-id]/page.tsx` lists a bot's channel configs
(`SlackChannelConfigsTable.tsx`); `bots/[bot-id]/channels/[id]/page.tsx` edits one.

A user who gets an answer in a public channel can click "Continue in web UI" to
open the same conversation as a real chat session, continuing where the Slack
thread left off.

---

## 2. Surfaces

### Admin web routes (`web/src/app/admin/bots/`)

| Route | File | Purpose |
|---|---|---|
| `/admin/bots` | `page.tsx` (`SlackBotTable.tsx`) | List installed Slack bots. |
| `/admin/bots/new` | `new/page.tsx` (`SlackBotCreationForm.tsx`) | Paste bot/app/user tokens, name the bot. |
| `/admin/bots/[bot-id]` | `[bot-id]/page.tsx` | Bot detail: tokens (`SlackBotUpdateForm.tsx`) and its channel configs (`SlackChannelConfigsTable.tsx`). |
| `/admin/bots/[bot-id]/channels/new` | `channels/new/page.tsx` (`SlackChannelConfigCreationForm.tsx`) | Create a channel config. |
| `/admin/bots/[bot-id]/channels/[id]` | `channels/[id]/page.tsx` | Edit a channel config. |

### HTTP endpoints (`onyx/server/manage/slack_bot.py`, router prefix `/manage`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/manage/admin/slack-app/bots` | `create_bot` | Validates tokens via `validate_tokens.py`; also creates a default (`is_default=True`) channel config with `respond_tag_only=True`. |
| PATCH | `/manage/admin/slack-app/bots/{slack_bot_id}` | `patch_bot` | Re-validates tokens on every save. |
| DELETE | `/manage/admin/slack-app/bots/{slack_bot_id}` | `delete_bot` | Cascades to its channel configs (`SlackBot.slack_channel_configs`, `cascade="all, delete-orphan"`). |
| GET | `/manage/admin/slack-app/bots`, `/manage/admin/slack-app/bots/{slack_bot_id}` | `list_bots`, `get_bot_by_id` | |
| GET | `/manage/admin/slack-app/bots/{bot_id}/config` | `list_bot_configs` | |
| POST/PATCH/DELETE | `/manage/admin/slack-app/channel[/{id}]` | `create_slack_channel_config`, `patch_slack_channel_config`, `delete_slack_channel_config` | Gated by `require_permission(Permission.MANAGE_BOTS)` on every route in this file. |
| GET | `/manage/admin/slack-app/channel` | `list_slack_channel_configs` | |
| POST | `/chat/seed-chat-session-from-slack` | `chat_backend.py:seed_chat_from_slack` | "Continue in web UI". Gated by `Permission.BASIC_ACCESS`, not `MANAGE_BOTS`: any authenticated user can seed from a Slack chat session ID they know. |

### Background process

`backend/onyx/onyxbot/slack/listener.py` runs as its own long-lived process
(`if __name__ == "__main__"`, not an ASGI app). One `SlackbotHandler` per pod
manages a `TenantSocketModeClient` per `(tenant_id, slack_bot_id)` pair, acquiring
tenants via a Redis lock (`OnyxRedisLocks.SLACK_BOT_LOCK`,
`config.py:TENANT_LOCK_EXPIRATION` = 1800s) so exactly one pod owns a tenant's
Slack bots at a time, up to `MAX_TENANTS_PER_POD` (default 50).

### Environment configuration (`backend/onyx/configs/onyxbot_configs.py`)

| Variable | Default | Effect |
|---|---|---|
| `ONYX_BOT_NUM_RETRIES` | 5 | Retries around the LLM call and around posting to Slack. |
| `ONYX_BOT_MAX_QPM` | unset (uncapped) | `SlackRateLimiter`'s per-process questions-per-minute gate. See §9. |
| `ONYX_BOT_MAX_WAIT_TIME` | 180 | Seconds a queued question waits before `TimeoutError`. |
| `ONYX_BOT_RESPONSE_LIMIT_PER_TIME_PERIOD` / `_TIME_PERIOD_SECONDS` | 5000 / 86400 | Global per-process message-volume cap, `utils.py:check_message_limit`. |
| `ONYX_BOT_DISABLE_DOCS_ONLY_ANSWER` | false | Suppress a reply that found no LLM answer, only documents. |
| `ONYX_BOT_DISPLAY_ERROR_MSGS` | false | Post the raw exception text into the thread on failure (see §9). |
| `NOTIFY_SLACKBOT_NO_ANSWER` | false | Post an apology message when `handle_message` returns "failed". |
| `ONYX_BOT_FEEDBACK_VISIBILITY` | `private` | Who sees the feedback confirmation message: `private`, `anonymous`, or `public`. |
| `ONYX_BOT_FEEDBACK_REMINDER` | 0 (off) | Minutes until a scheduled DM reminder to leave feedback. |
| `ONYX_BOT_REACT_EMOJI` / `ONYX_BOT_FOLLOWUP_EMOJI` | `eyes` / `sos` | Reaction emoji while thinking / for follow-up requests. |
| `MAX_TENANTS_PER_POD` | 50 | Cloud scaling knob, `onyxbot/slack/config.py`. |

---

## 3. Data model

### `slack_bot` (`SlackBot`, `db/models.py:SlackBot`)

| Column | Meaning |
|---|---|
| `name` | Admin label. |
| `enabled` | Soft-disable; `listener.py:prefilter_requests` drops every event for a disabled bot. |
| `bot_token` | `EncryptedString`, unique. The `xoxb-` token used for `WebClient` (post messages, read channel info). |
| `app_token` | `EncryptedString`, unique. The `xapp-` token used only to open the Socket Mode WebSocket. |
| `user_token` | `EncryptedString`, nullable. Validated (`validate_user_token`). The listener path does not read it. Federated Slack search reads it (`search_tool.py:_prefetch_slack_data`, see §9). |

Both `bot_token` and `app_token` are validated against live Slack API calls
(`server/manage/validate_tokens.py:validate_bot_token`, `validate_app_token`) on
every create and update, before the row is written.

### `slack_channel_config` (`SlackChannelConfig`, `db/models.py:SlackChannelConfig`)

| Column | Meaning |
|---|---|
| `slack_bot_id` | FK to the owning bot. |
| `persona_id` | Nullable FK to `Persona`. `None` falls back to `DEFAULT_PERSONA_ID` at answer time (`handle_regular_answer.py`). |
| `channel_config` | JSONB, typed as `ChannelConfig` (`db/models.py:ChannelConfig`, a `TypedDict`). See table below. |
| `enable_auto_filters` | Whether to auto-detect search filters for this channel. |
| `is_default` | Exactly one default config per bot (`uq_slack_channel_config_slack_bot_id_default`); used when no channel-specific config matches. |
| `standard_answer_categories` | M2M to `StandardAnswerCategory` via `slack_channel_config__standard_answer_category`. EE-only concept; see [[standard-answers]]. |

### `ChannelConfig` fields (inside the JSONB column)

| Field | Meaning |
|---|---|
| `channel_name` | `None` for the default config, else the Slack channel name (no `#`). |
| `respond_tag_only` | Only answer when `@OnyxBot` is tagged or the message is a DM. New bots default this to `True` (`server/manage/slack_bot.py:create_bot`). |
| `respond_to_bots` | Whether to answer messages posted by other bots. |
| `is_ephemeral` | Post the answer visible only to the asker (`chat_postEphemeral`) instead of into the channel. |
| `respond_member_group_list` | Allowlist of emails/user-group names. Doubles as an invocation gate (who can trigger the bot at all) and, when set, as the ephemeral-visibility scope. See §5 and §9. |
| `answer_filters` | `questionmark_prefilter` (skip non-questions) and/or `well_answered_postfilter` (skip answers with no citations). |
| `follow_up_tags` | Slack user/group tags to notify when a user requests human follow-up; presence (even empty list) enables the follow-up feature. |
| `show_continue_in_web_ui` | Show the "Continue in web UI" button. |
| `disabled` | Only meaningful on the default config; disables the bot for the whole channel including DMs. |

### Redis / cache keys

| Key | Owner | Meaning |
|---|---|---|
| `OnyxRedisLocks.SLACK_BOT_LOCK` (per tenant) | `listener.py:acquire_tenants` | Exclusive ownership of a tenant's Slack sockets by one pod. |
| `OnyxRedisLocks.SLACK_BOT_HEARTBEAT_PREFIX:{pod_id}` | `listener.py:send_heartbeats` | Liveness signal, not itself gating ownership. |

In-process (not Redis, not shared across pods): `slack_token_user_ids` /
`slack_token_bot_ids` caches (`utils.py`, keyed by `(tenant_id, slack_bot_id)`), and
`SlackRateLimiter`'s counters (`utils.py:SlackRateLimiter`).

---

## 4. How it works

### 4.1 The call chain (event to posted answer)

```
create_process_slack_event -> process_slack_event   listener.py
  ├─ acknowledge_message                              listener.py   (must ack fast or Slack assumes the bot is dead)
  ├─ _check_tenant_gated                               listener.py   (cloud license/trial gate)
  └─ process_message                                   listener.py
       ├─ prefilter_requests                            listener.py  (self-message, greetings, disabled bot, subtype filtering)
       ├─ build_request_details                          listener.py -> SlackMessageInfo
       ├─ get_slack_channel_config_for_bot_and_channel    config.py
       ├─ schedule_feedback_reminder                      handle_message.py
       └─ handle_message                                  handlers/handle_message.py
            ├─ _resolve_allowlist_user_ids                  (invocation gate + visibility scope)
            ├─ add_slack_user_if_not_exists / get_user_by_email   db/users.py  (identity mapping, see §5)
            ├─ handle_standard_answers                       handlers/handle_standard_answers.py -> EE impl
            └─ handle_regular_answer                          handlers/handle_regular_answer.py
                 ├─ get_persona_by_id                           db/persona.py  (persona access check)
                 ├─ handle_stream_message_objects                chat/process_message.py   <-- direct in-process call
                 ├─ gather_stream                                chat/process_message.py
                 └─ build_slack_response_blocks / respond_in_thread_or_channel   blocks.py / utils.py
```

### 4.2 Installation and connection

An admin creates tokens in Slack's API console (Socket Mode app), pastes the bot
token (`xoxb-`) and app token (`xapp-`) into `SlackBotCreationForm.tsx`, which
posts to `create_bot` (`server/manage/slack_bot.py`). Both tokens are round-tripped
to Slack (`validate_bot_token`, `validate_app_token`) before the row is written;
an invalid token is rejected at save time, not silently stored.

The listener process (`listener.py:SlackbotHandler`) polls every
`TENANT_ACQUISITION_INTERVAL` (60s) for tenants with enabled bots, opens a
`TenantSocketModeClient` per `(tenant_id, slack_bot_id)`
(`listener.py:_get_socket_client`, `start_socket_client`), and appends
`process_slack_event` as its event listener. A token change is detected by
comparing the cached `SlackBotTokens` and triggers a full reconnect
(`_manage_clients_per_tenant`).

### 4.3 Channel resolution and filtering

`get_slack_channel_config_for_bot_and_channel` (`config.py`) looks up a config by
`channel_config["channel_name"]`, falling back to the bot's `is_default` config
(`db/slack_channel_config.py:fetch_slack_channel_config_for_channel_or_default`).
`handle_message` then applies, in order: the `respond_member_group_list`
invocation gate, `answer_filters` (question-mark prefilter), `disabled`, and
`respond_tag_only` (unless tagged or a DM).

### 4.4 Identity mapping (security-relevant, see §5)

`build_request_details` resolves the Slack sender to an email via
`expert_info_from_slack_id` (a Slack API call). `handle_message` then, given an
email: checks invite/domain policy (`verify_email_is_invited`,
`verify_email_domain`), checks license seat availability, and calls
`add_slack_user_if_not_exists` (`db/users.py`), which looks up or creates an Onyx
`User` row for that email (promoting an `EXT_PERM_USER` to `BOT` account type if
needed). This is how a Slack identity becomes (or reuses) an Onyx account. If
`message_info.email` is `None` (Slack lookup failed or user has no email), none of
this runs and no Onyx account is touched for that turn.

`handle_regular_answer` then independently resolves `resolved_user =
get_user_by_email(...)` and decides which identity actually drives the search:
see §5 for the exact rule.

### 4.5 Standard answers (before the LLM)

`handle_standard_answers` (`handlers/handle_standard_answers.py`) dispatches via
`fetch_versioned_implementation` to the EE implementation
(`ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py:_handle_standard_answers`)
when EE is active, else a CE no-op that always returns `False`. The EE version
matches the message against the channel's configured
`standard_answer_categories`, excluding answers already used in this Slack
thread (tracked via `chat_message__standard_answer`), creates a real
`ChatSession`/`ChatMessage` pair so the answer is recorded, and posts the answer
with a "Generate Full Answer" button. See [[standard-answers]]. If a standard
answer matches, `handle_regular_answer` (and the LLM) never runs for this
message.

### 4.6 The regular-answer turn (in-process, not HTTP)

`handle_regular_answer` builds a `SendMessageRequest` with
`origin=MessageOrigin.SLACKBOT`, then calls
`chat/process_message.py:handle_stream_message_objects` and `gather_stream`
**directly as Python functions**, inside the same process as the listener. It
never issues an HTTP request to `POST /chat/send-chat-message`
(`chat_backend.py:handle_send_chat_message`), so it never goes through that
endpoint's FastAPI `Depends` chain. See §5 and §9 for what that skips.

It passes
`slack_context=message_info.slack_context` (drives federated Slack search,
[[internal-search]], `_should_enable_slack_search`,
`context/search/federated/slack_search.py`) and
`additional_context=slack_context_str` (prior thread messages, formatted by
`build_slack_context_str`, injected as extra LLM context, never persisted to the
DB per the `additional_context` docstring in `process_message.py`).

Retries (`@retry_builder`, `ONYX_BOT_NUM_RETRIES`) and the in-process rate limiter
(`@rate_limits`, `SlackRateLimiter`) wrap the call; see §9 for what they do and do
not protect against.

### 4.7 Formatting and posting

`build_slack_response_blocks` (`blocks.py:448`) assembles the Slack Block Kit
payload: the main answer text via `_build_main_response_blocks`, source citations
via `_build_sources_blocks` / `_build_citations_blocks`, feedback buttons
(`get_document_feedback_blocks`), and, if configured, a "Continue in web UI"
button (`_build_continue_in_web_ui_block`, encoding a
`build_continue_in_web_ui_id`). `respond_in_thread_or_channel` (`utils.py`) posts
via `chat_postMessage` or, for an allowlisted/ephemeral scope,
`chat_postEphemeral` per receiver, retrying once with URL-containing blocks
stripped if Slack rejects the payload (`_check_for_url_in_block`).

### 4.8 Continuing in the web app

The "Continue in web UI" button encodes a `chat_message_id`
(`build_continue_in_web_ui_id`). Clicking it drives the frontend to call
`POST /chat/seed-chat-session-from-slack`
(`chat_backend.py:seed_chat_from_slack`), which calls
`duplicate_chat_session_for_user_from_slack` (creates a new `ChatSession` owned by
the clicking user, re-resolving the persona through that user's own access via
`get_best_persona_id_for_user`) and `add_chats_to_session_from_slack_thread`
(copies the message history, `db/chat.py`), then redirects to
`{WEB_DOMAIN}/chat?chatId=...`. Both DB functions read the source Slack chat
session with `user_id=None` / `skip_permission_check=True`, since the reader at
that point is not the message's original asker.

---

## 5. Contracts and invariants

1. **The answer must respect the asking user's actual document access, and the
   verified mechanism is narrower than "the mapped Onyx user's ACLs".**
   `handle_regular_answer.py` computes `can_search_over_private_docs =
   message_info.is_bot_dm or send_as_ephemeral`. Only when that is true does the
   turn run as the resolved (or newly provisioned) Onyx user; in every ordinary
   channel post, it runs as `get_anonymous_user()` regardless of whether the
   sender mapped to a real Onyx account, restricting the search to public
   documents. `handle_stream_message_objects` (`process_message.py`) takes no
   ACL-bypass flag; the only lever is which `user` gets passed in
   (`handle_regular_answer.py:_get_slack_answer`, `onyx_user=` argument). Cross-link [[access-control]].
2. **An unmapped Slack user (no resolvable email) never gets elevated access.**
   With `message_info.email is None`, `resolved_user` is `None`, the effective
   user is `get_anonymous_user()`, and the account-provisioning block in
   `handle_message.py` is skipped entirely. An unmapped user in a DM or ephemeral
   context still only gets the anonymous user, the same public-doc-only scope as
   a public channel post; nothing in the code path grants a private-doc identity
   without a resolved email. This is verified directly from the code above, not
   assumed.
3. **The bot must not post secrets or leak internal errors into a channel by
   default.** `ONYX_BOT_DISPLAY_ERROR_MSGS` (default enabled in this codebase,
   see §9) controls whether a raw Python exception string is posted into the
   thread on failure; anyone touching error handling in `handle_regular_answer`
   must keep this gate.
4. **A failed turn must degrade visibly, not silently.** `handle_message`
   returns `True` ("failed") on genuine failures (persona access denial and the
   usage-budget reply post their own message, cancel the feedback reminder,
   and return `False`; document-search or LLM failure returns `True`), and `process_message` in `listener.py` posts
   `apologize_for_fail` when `notify_no_answer` (`NOTIFY_SLACKBOT_NO_ANSWER`) is
   set. A change that swallows an exception without hitting one of these paths
   leaves the user staring at an eyes-emoji reaction forever.
5. **Protections enforced by the HTTP dependency chain on
   `/chat/send-chat-message` are not automatically present here.** Because
   `handle_regular_answer` calls `handle_stream_message_objects` /
   `gather_stream` directly, any check implemented as a FastAPI `Depends` on
   `chat_backend.py:handle_send_chat_message` must be either re-implemented in
   the Slack path or consciously accepted as absent. See §9 for the current,
   verified list.
6. **`is_default` is unique per bot, and channel config lookup falls back to it
   silently** (`fetch_slack_channel_config_for_channel_or_default`). Deleting or
   corrupting the default config makes `get_slack_channel_config_for_bot_and_channel`
   raise (`config.py:18`), which fails the whole channel resolution for every
   unconfigured channel of that bot.
7. **Tokens are always re-validated against Slack on write**
   (`validate_bot_token`, `validate_app_token`), never just stored as-typed.

---

## 6. Relationships

**Depends on**
- [[core-chat-loop]]: `handle_stream_message_objects` and `gather_stream` are the
  same functions `chat_backend.py:handle_send_chat_message` calls; a change to
  the turn engine's behavior reaches the Slack bot without a code change here.
- [[standard-answers]]: matched before the LLM runs; EE-gated.
- [[agents-personas]]: `slack_channel_config.persona_id` selects the persona and
  its document sets, tools, and prompt.
- [[access-control]]: the anonymous-vs-real-user split in `handle_regular_answer`
  is the entire ACL story for this surface; see §5.
- [[auth-and-identity]]: `add_slack_user_if_not_exists`, invite/domain
  verification, and seat-limit checks all reuse the same auth primitives as
  self-serve signup.
- [[internal-search]]: the persona's search tool is force-enabled on the first
  cycle when available; Slack-as-search-source (`slack_search.py`) is a
  *different* mechanism, see below.
- [[chat-persistence]]: standard answers and regular answers both create real
  `ChatSession`/`ChatMessage` rows via the same tables `save_chat_turn` writes.
- [[rate-and-usage-limits]]: `check_token_rate_limits(usage_user)` runs
  before each answer; see §9 for why it must be called inline.

**Depended on by**
- [[chat-persistence]]: seeded web sessions from
  `/chat/seed-chat-session-from-slack` are ordinary `ChatSession` rows afterward.
- Nothing depends on this component as infrastructure; it is a leaf consumer of
  the chat loop.

**Distinct from (do not conflate)**
- Slack as a **search source**: `backend/onyx/context/search/federated/slack_search.py`
  lets the chat loop's search tool query live Slack messages/channels as a
  retrieval source, gated by `_should_enable_slack_search` and
  `SearchTool`'s `slack_context`. This runs for *any* chat turn (web, API, or Slack bot) whose
  persona/filters select the Slack source, and requires a **federated Slack
  connector**, a separate config from `SlackBot`/`SlackChannelConfig`. The Slack
  *bot* (this document) is the inbound event listener that turns a Slack message
  into a chat turn; Slack *search* is one retrieval source that turn's tools can
  query. A Slack bot channel config with no document sets and a persona whose
  tools include Slack search can still answer using content from other Slack
  channels via `slack_search.py`, independent of `respond_...` filtering.
  Cross-link [[internal-search]].

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| changes the turn entry point (`handle_stream_message_objects`, `gather_stream`, or `build_chat_turn`'s signature) | `handlers/handle_regular_answer.py:_get_slack_answer`, since the bot calls these directly and in-process, not through `chat_backend.py`; a signature change breaks the bot at import/call time, not at request time |
| adds a new FastAPI dependency to `POST /chat/send-chat-message` | it will **not** run for Slack-originated turns; decide whether the check belongs in `handle_message.py` / `handle_regular_answer.py` too, or is acceptably web-only |
| changes `ChannelConfig` (adds/renames a field) | `server/manage/slack_bot.py:_form_channel_config`, every `web/src/app/admin/bots/[bot-id]/channels/*` form, and `handle_message.py`'s reads of `channel_conf` |
| changes identity mapping (`add_slack_user_if_not_exists`, `get_anonymous_user`, the `can_search_over_private_docs` condition) | [[access-control]]; this is the one place document-access scope is decided for this surface, re-verify with a live test, not just code reading |
| changes `SlackBot` token fields or their encryption | `server/manage/validate_tokens.py`, `listener.py:_manage_clients_per_tenant`'s token-diff/reconnect logic |
| changes standard-answer matching or its EE/CE dispatch | [[standard-answers]]; `_handle_standard_answers`'s "already used in this thread" de-dup reads `chat_message__standard_answer`, so a change to chat message persistence can silently break de-dup |
| changes Slack Block Kit payload shape (`blocks.py`) | Slack's 50-block hard limit (`handle_regular_answer.py`'s `all_blocks[:50]`), and the URL-stripping retry path in `utils.py:respond_in_thread_or_channel` |
| changes multi-tenant Slack bot scaling (`listener.py`'s locks, `MAX_TENANTS_PER_POD`) | cloud only; a self-hosted single-tenant deployment does not exercise the lock-contention paths |

---

## 8. How to verify a change

### Tests

```bash
# Unit: channel config resolution, block formatting, socket client lifecycle, gating
cd backend && uv run pytest tests/unit/onyx/onyxbot

# External dependency unit: real Slack bot CRUD against a live-ish Slack API surface,
# and federated search wiring
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/slack_bot

# Slack-as-connector integration tests (permission sync, pruning). These exercise
# Slack as a document source, not the bot, but changes to Slack API usage in
# onyxbot/slack/utils.py can affect both
uv run --env-file .vscode/.env pytest backend/tests/integration/connector_job_tests/slack

# Slack user deactivation / seat interaction
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/users/test_slack_user_deactivation.py
```

See `backend/AGENTS.md` for required env and secrets.

### Manual reproduction

1. Confirm the listener process is running: `tail -f backend/log/slack_bot_debug.log`
   (or the process's configured log target).
2. In Slack, create/paste a bot+app token pair at `/admin/bots/new`; confirm the
   save fails with a clear error on an invalid token (`validate_bot_token`).
3. Configure a channel (`/admin/bots/[bot-id]/channels/new`) with a persona and a
   document set, `respond_tag_only` off.
4. Post a plain message in that channel. Confirm the eyes-emoji reaction appears,
   then an answer with citations posts in-thread.
5. Post a message matching a configured standard answer (if EE). Confirm it
   answers instantly with the "Generate Full Answer" button and no LLM latency.
6. DM the bot as a user with no existing Onyx account. Confirm a new account is
   provisioned (or blocked with a clear message if invite-only/seat-limited).
7. Click "Continue in web UI" on a public-channel answer. Confirm the new web
   chat session shows the same history under the clicking user's account.

### What "working" looks like

- Public-channel answers never surface content the anonymous user could not
  otherwise see; DM/ephemeral answers only surface private content for the
  resolved sender's own account.
- A malformed or over-limit Block Kit payload still posts something (the
  URL-stripped retry), never a silent drop.
- Disabling a bot or a channel config stops all replies within one
  `TENANT_ACQUISITION_INTERVAL` (60s) cycle.

---

## 9. Footguns

- **The Slack bot skips the HTTP dependency chain on
  `/chat/send-chat-message`, so every metering check must be called inline.**
  `handle_regular_answer.py` calls `handle_stream_message_objects` and
  `gather_stream` from `chat/process_message.py` directly. It calls
  `check_token_rate_limits(usage_user)` itself, before the retry wrapper, and
  replies with the budget message on `RATE_LIMITED`. When the sender has no
  Onyx account, `usage_user` is the Slack service account, which the EE check
  holds to GLOBAL budgets only, so a per-user budget cannot silence the bot
  for every unmapped user at once ([[rate-and-usage-limits]] §4.1). The cloud cost cap runs
  inside `process_message`. `check_api_key_usage` does not apply, because no
  API key is involved. `SlackRateLimiter` (`onyxbot/slack/utils.py`,
  `ONYX_BOT_MAX_QPM`, uncapped by default) is a separate in-memory QPM gate
  with no cross-pod coordination, not a budget. Tests that drive
  `handle_regular_answer` against the shared DB must patch the budget check,
  or leftover budgets from other suites fail them.
- **Public-channel answers use the anonymous user regardless of who is asking.**
  `can_search_over_private_docs = message_info.is_bot_dm or send_as_ephemeral`
  is the only gate; a resolved, fully-permissioned Onyx user asking in an
  ordinary channel still gets `get_anonymous_user()`'s document scope. This is
  intentional (prevents leaking private-doc content into a shared channel) but
  is easy to mistake for a bug when a user reports "the bot can't see documents
  I have access to."
- **`ONYX_BOT_DISPLAY_ERROR_MSGS` defaults to enabled**, because the config
  computes `not in ["false", ""]` against an unset (empty-string) env var. A
  raw Python exception, including tool arguments and possibly parts of a
  document, is posted into the Slack thread on failure unless an operator
  explicitly sets it to `"false"`.
- **`respond_member_group_list` is a single allowlist doing two jobs.** It gates
  who can invoke the bot at all (before answer processing, before user provisioning) and
  also scopes who sees the ephemeral response. Configuring it wrong (e.g. an
  admin expecting it to only affect visibility) silences the bot for everyone
  else in the channel, including tags and DMs.
- **A deleted Slack bot's socket can keep delivering events until the next
  acquisition cycle** (`listener.py:_drop_stale_bots`'s docstring says so
  directly); events are acked before the bot row is checked, so Slack never
  retries them, but the process may still briefly act on a bot that no longer
  exists in the DB (guarded by `prefilter_requests`'s `slack_bot is None` check,
  which then drops the request).
- **`user_token` is validated on every save and feeds federated Slack search.**
  `SearchTool._prefetch_slack_data` (`tools/tool_implementations/search/search_tool.py`)
  prefers an enabled bot row that has a `user_token`. It then sets
  `access_token = user_token or bot_token`. Federated Slack search uses the user
  token when one is set.
- **Standard-answer de-duplication is thread-scoped, not global**: the same
  standard answer can be given again in a different Slack thread even if a user
  already saw it elsewhere, because `used_standard_answer_ids` is computed from
  `get_chat_sessions_by_slack_thread_id` for the current thread only.

### Legacy callhome removal

Slack queries use fleet query instrumentation. Legacy usage reporting and its extra Slack email lookup are removed.
`listener.py:main` starts the bounded fleet sender before the handler starts its message-processing threads.
Its `finally` block closes telemetry on normal exit, startup failure, and signal-driven exit without waiting for delivery.
Invocation gates, user provisioning, and permission checks are unchanged.
