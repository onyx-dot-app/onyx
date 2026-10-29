# Slack Bot

> A separate listener process answers questions in Slack: it turns each Slack
> event into an in-process chat turn and posts the answer to the thread. It skips
> the HTTP chat route, so each check on that route must be repeated here or
> accepted as absent.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE for the listener and the answer path. Standard answers are EE
([[standard-answers]]). Tenant acquisition across pods matters only on cloud.

---

## User experience

- **A Slack user** tags the bot, sends it a DM, or posts in a channel that is
  set to answer every message. The bot adds a reaction while it works, then
  replies in the thread with the answer, its sources and feedback buttons. A
  configured channel can also show "Continue Chat in Onyx", which opens the
  conversation as a web chat session. The copy keeps the text, files and
  final reasoning of each message, but no tool calls or sources.
- **In a public channel, the answer uses only indexed documents that an
  anonymous user can see,** even when the asker has wider access. Federated
  Slack results do not follow this rule ([[#public-channel-anonymous-search]]).
  In a DM, a slash command, or a channel set to ephemeral replies, the answer
  uses the Onyx account for the sender's Slack email. The bot creates that
  account on first contact. When Slack gives no email, the answer uses the
  anonymous user's access. Users who report "the bot cannot see my documents"
  usually meet this rule. The asker of an ephemeral answer can click "Share with
  Everyone" to post it in the thread for the whole channel
  ([[#share-with-everyone-publishes]]).
- **A refusal is posted, not silent,** when the asker cannot use the channel's
  agent, a token budget is reached, the workspace is invite-only or
  domain-restricted, or no seat is free. A gated tenant or an expired license
  gets a "subscription has expired" reply.
- **Other failures are silent by default.** The reaction goes away and nothing
  is posted. An operator can turn on an apology (`NOTIFY_SLACKBOT_NO_ANSWER`)
  or the raw exception text (`ONYX_BOT_DISPLAY_ERROR_MSGS`). Both are off when
  unset.
- **An admin** with the manage-bots permission adds a Slack app at Admin > Bots
  with a bot token and an app token. The API validates the tokens before it
  saves them. Socket Mode needs no public webhook URL. The admin then
  configures channels: the agent or document sets, tag-only or every message,
  ephemeral replies, an allowlist of users and groups, answer filters,
  follow-up tags, and standard-answer categories. The customer setup guide is
  `documentation/admins/getting_started/slack_bot_setup.mdx`.

---

## Scope

This component owns the listener process and its tenant acquisition, the event
filters, the message and button handlers, the Block Kit replies, the Slack bot
and channel config records with their admin API and admin pages, and the
per-process message limiters (`SlackRateLimiter`, `check_message_limit`).

Its neighbours own:
- [[core-chat-loop]]: the turn that the bot runs in-process.
- [[standard-answers]]: the canned-answer match that runs before the turn.
- [[rate-and-usage-limits]]: token budgets. The bot only calls the check.
- [[federated-search]]: Slack as a live search source. It reads a Slack bot's
  tokens but is a separate feature.
- [[slack]]: the Slack connector. The bot imports some of its helpers.
- [CROSS-CUTTING.md: Who is the acting user](../CROSS-CUTTING.md#who-is-the-acting-user):
  the acting-user rules for Slack and the other surfaces.

---

## Architecture

```
SlackbotHandler, every 60 s: acquire_tenants         one socket client per
  _manage_clients_per_tenant                         (tenant_id, slack_bot_id)
process_slack_event                                  per event
  acknowledge_message                                ack first, or Slack retries
  _check_tenant_gated                                cloud gating, expired license
  action_routing / view_routing                      buttons and modals (handle_buttons.py)
  process_message
    prefilter_requests                               disabled bot, self, greetings,
                                                     subtypes, non-root thread replies,
                                                     check_message_limit
    build_request_details                            sender email via Slack API
    get_slack_channel_config_for_bot_and_channel     by channel name, else default
    handle_message                                   handlers/handle_message.py
      allowlist gate, filters, tag-only
      provision Slack user (invite, domain, seat)
      handle_standard_answers -> True: stop
      handle_regular_answer                          handlers/handle_regular_answer.py
        persona access check, check_token_rate_limits
        handle_stream_message_objects + gather_stream   in-process, origin SLACKBOT
        build_slack_response_blocks, respond_in_thread_or_channel
```

**Process and tenancy.** `onyx/onyxbot/slack/listener.py` runs as its own
process (the supervisord `slack_bot` program, the Helm `slackbot` deployment). A
Redis lock per tenant (`OnyxRedisLocks.SLACK_BOT_LOCK`) lets one pod own a
tenant's sockets. Token changes and deleted bots reach the sockets only at the
next acquisition cycle. Until then `prefilter_requests` drops events for a
missing or disabled bot.

**Identity.** `handle_message` provisions every sender who passes the channel
filters and has a resolvable email
(`db/users.py:add_slack_user_if_not_exists`), before the answer path. Then
`handle_regular_answer` picks two identities. The search runs as the mapped
user or the anonymous user. Usage is charged to the mapped user, or to the
Slack service account (`get_or_create_slack_service_account`) when no user
matches. The service account gets GLOBAL budgets only, so a per-user
budget cannot silence the bot for every unmapped sender
([[rate-and-usage-limits#shared-principals-global-only]]).
[[#public-channel-anonymous-search]] is the trap.

**Context.** Earlier thread messages go to the turn as `additional_context`
(`build_slack_context_str`), which the chat loop does not persist. The message
carries `slack_context`, which lets the search tool run federated Slack search
when the persona's document sets link a Slack federated connector
(`tools/tool_implementations/search/search_tool.py:SearchTool._prefetch_slack_data`).
The turn forces the search tool on the first cycle when the persona has an
enabled one and `SearchTool.is_available` is true.

**Channel-only agents.** When an admin picks document sets instead of an agent,
`db/slack_channel_config.py:create_slack_channel_persona` creates a public
persona named with `SLACK_BOT_PERSONA_PREFIX`. Persona lists hide these by that
prefix. Deleting the channel config marks that persona deleted.

---

## Contracts and traps

1. `chat-route-depends-skipped` **Checks that are a `Depends` on the HTTP chat
   route do not run here.**
   `onyxbot/slack/handlers/handle_regular_answer.py:handle_regular_answer` calls
   `chat/process_message.py:handle_stream_message_objects` directly, so it
   skips the dependency chain on
   `server/query_and_chat/chat_backend.py:handle_send_chat_message`. It calls
   `check_token_rate_limits(usage_user)` inline for that reason.
   `check_api_key_usage` does not apply, because no API key is involved. Add a
   new chat-route check to `handle_regular_answer` before `_get_slack_answer`,
   or accept it as web-only. Tests that drive `handle_regular_answer` on the
   shared database must patch the budget check, or budgets left by other suites
   fail them.
2. `public-channel-anonymous-search` **Public-channel answers search as the
   anonymous user.** `can_search_over_private_docs = message_info.is_bot_dm or
   send_as_ephemeral` in `handle_regular_answer` is the only switch, and for indexed documents the only
   lever is the `onyx_user` passed to `_get_slack_answer`. Do not pass the
   mapped user in a shared channel. It would post private document content
   where others can read it. Keep the persona access check on the mapped user,
   as it is: it decides who may use the channel's agent. Federated Slack
   results ignore `onyx_user`: the bot install's token and the channel-type
   rules in [[federated-search]] decide what they show.
3. `respond-ignores-ephemeral-flag` **`respond_in_thread_or_channel` ignores
   `send_as_ephemeral`.** The parameter is marked unused
   (`onyxbot/slack/utils.py:respond_in_thread_or_channel`). A non-empty
   `receiver_ids` posts one ephemeral message for each receiver, and an empty
   one posts publicly. Callers decide visibility only through `receiver_ids`.
4. `allowlist-gates-and-receives` **`respond_member_group_list` does two
   jobs.** `onyxbot/slack/handlers/handle_message.py:handle_message` uses it
   as an invocation gate before provisioning,
   so a sender who is not on the list gets no answer, not even for a tag or a
   DM. It is also the receiver list, so every answer goes ephemerally to each
   listed user. If no entry resolves, the bot is silent in that channel and
   logs an error. The admin API rejects an allowlist together with
   `is_ephemeral` (`server/manage/slack_bot.py:_form_channel_config`).
5. `default-channel-config-required` **The default channel config must
   exist.** `server/manage/slack_bot.py:create_bot` creates one with
   `is_default=True` and tag-only on.
   Channel lookup falls back to it
   (`db/slack_channel_config.py:fetch_slack_channel_config_for_channel_or_default`).
   If it is deleted,
   `onyxbot/slack/config.py:get_slack_channel_config_for_bot_and_channel` raises for
   every channel that has no config of its own. The delete endpoint does not
   block this. Lookup is by channel name, so a renamed Slack channel falls back
   to the default config.
6. `failed-turn-silent` **A failed turn is silent unless it returns `True`.**
   `handle_message` returns `True` only for an answer failure. Policy refusals
   post their own message and return `False`.
   `onyxbot/slack/listener.py:process_message` posts the
   apology only for `True` and only when `NOTIFY_SLACKBOT_NO_ANSWER` is on. An
   exception that escapes another way leaves the reaction in place with no
   reply.
7. `display-error-msgs-leaks` **`ONYX_BOT_DISPLAY_ERROR_MSGS` posts raw
   exception text.** It is off when unset. When on, `handle_regular_answer`
   posts the exception string into the thread, which can include tool arguments
   or document text. Keep it behind this flag.
8. `ack-before-work` **Acknowledge before any work.**
   `process_slack_event`, built by
   `onyxbot/slack/listener.py:create_process_slack_event`, calls
   `acknowledge_message` first, because Slack treats a slow ack as a dead
   bot. Slack never retries an acked event, so a crash after the ack loses it.
9. `block-payload-limits` **Block payloads have hard limits.**
   `handle_regular_answer` cuts the block list to 50.
   `respond_in_thread_or_channel` retries once without blocks that contain URLs
   when Slack rejects a payload. A change to `onyxbot/slack/blocks.py` must
   keep both paths working.
10. `root-messages-only` **Only root messages start a turn in a channel.**
    `onyxbot/slack/listener.py:prefilter_requests` drops a thread reply unless it tags the bot or is in a
    DM. A follow-up in a channel thread therefore needs a tag.
11. `share-with-everyone-publishes` **"Share with Everyone" posts the asker's
    private answer publicly.** An ephemeral reply to one receiver searches with
    the asker's ACL ([[#public-channel-anonymous-search]]) and offers the button
    (`offer_ephemeral_publication` in `onyxbot/slack/blocks.py`).
    `onyxbot/slack/handlers/handle_buttons.py:handle_publish_ephemeral_message_button`
    rebuilds the answer and its sources from the saved `ChatMessage` and posts
    them with `receiver_ids=None`. No access check runs for the channel
    audience. The asker's click is the only gate.

---

## Decisions

- **Anonymous search in shared channels.** Slack channel membership does not
  match Onyx document ACLs, so a shared channel gets public documents only.
  The one exception is an ephemeral answer that its asker publishes.
- **The allowlist is a seat gate, not a content filter.** Each new sender
  takes a seat on first contact, so `handle_message` checks the allowlist
  before it provisions.

---

## Known issues

- **"Generate Full Answer" skips the `handle_message` gates.**
  `onyxbot/slack/handlers/handle_buttons.py:handle_generate_answer_button`
  calls `handle_regular_answer` directly with `receiver_ids=None`. It does not
  check the allowlist, invite or seat rules, and it posts publicly unless the
  channel is ephemeral.
- **The publish button reloads the message without its owner.** If
  `get_chat_message` fails for the asker, the handler retries with no user id,
  which succeeds only for a session that no user owns.
- **The slash-command refusal does not stop the answer.** With an allowlist,
  `handle_message` posts "The OnyxBot slash command is not enabled for this
  channel" and then goes on to answer.
- **In-process limits are per process, not per tenant.**
  `onyxbot/slack/utils.py:check_message_limit` keeps one global counter, so on
  cloud one tenant's traffic can use up the limit for every tenant on that pod.
  It drops messages with no reply. `SlackRateLimiter` (`ONYX_BOT_MAX_QPM`, off
  by default) is also per process.
- **Federated Slack search may use another bot's token.**
  `SearchTool._prefetch_slack_data` picks the first enabled bot that has a user
  token, else the first enabled bot. It does not pick the bot that received the
  message.

---

## Dependencies

- [[core-chat-loop]]: a change to `handle_stream_message_objects` or `chat/process_message.py:gather_stream` reaches the bot with no change here. `gather_stream` joins every root answer section and skips child-agent packets.
- [[standard-answers]]: runs before the regular answer and can end the turn.
- [[agents-personas]]: the channel's persona sets the prompt, tools and document sets.
- [[access-control]]: the anonymous user's scope bounds public-channel answers.
- [[auth-and-identity]]: invite, domain and seat checks during provisioning.
- [[rate-and-usage-limits]]: the inline budget check.
- [[editions-and-gating]]: standard answers and seat checks load through EE fallbacks.
- [[multi-tenancy]]: tenant locks and the tenant context of each socket client.
- [[chat-persistence]]: bot turns and "Continue Chat in Onyx" sessions are normal `ChatSession` rows; `db/chat.py:duplicate_chat_session_for_user_from_slack` copies only sessions owned by no user, the anonymous user or the caller.
- [[slack]]: the bot imports helpers from `connectors/slack/utils.py` and `connectors/slack/source_operations.py`.

---

## Recipes

- `add-channel-setting` **Add a channel setting.** Copy `respond_to_bots`. Add the key to
  `db/models.py:ChannelConfig` and to
  `server/manage/models.py:SlackChannelConfigCreationRequest`, set it in
  `server/manage/slack_bot.py:_form_channel_config`, and read it where the rule
  applies (`prefilter_requests` reads `respond_to_bots`; most settings are read
  in `handle_message` or `handle_regular_answer`). Add the field to the forms
  under `web/src/app/admin/bots/[bot-id]/channels/`. List the current settings
  in the `ChannelConfig` TypedDict. The config is a JSONB column and existing
  rows lack the new key, so read it with `.get` and a default.
- `investigate-no-answer` **Investigate "the bot did not answer".** Read the `slack_bot` process log.
  A `process_message prefiltered` line means `prefilter_requests` dropped the
  event: check for a disabled bot, a thread reply with no tag
  ([[#root-messages-only]]), or the message limit. A "not in
  respond_member_group_list" line is the allowlist gate
  ([[#allowlist-gates-and-receives]]). A raise from
  `get_slack_channel_config_for_bot_and_channel` means the default config is
  gone ([[#default-channel-config-required]]). No socket at all after a token
  change can mean the socket failed to start:
  `SlackbotHandler._manage_clients_per_tenant` stores the new tokens first, so
  it does not retry until the tokens change again. Set
  `NOTIFY_SLACKBOT_NO_ANSWER` to see answer failures in the thread.
- `investigate-private-doc-in-answer` **Investigate a private document in a
  channel answer.** Check these paths in
  order: the federated Slack lane ([[#public-channel-anonymous-search]]), a
  published ephemeral answer ([[#share-with-everyone-publishes]]), a "Generate
  Full Answer" post (Known issues), a chunk ACL that permission sync has not
  yet updated ([[permission-sync]]), and a connector that marks the document
  public.
- `run-listener-locally` **Run the listener locally.** Use the "Slack Bot" entry in
  `.vscode/launch.json`, or run `onyx/onyxbot/slack/listener.py` from
  `backend/`. Create a Slack app with Socket Mode on, add it at Admin > Bots,
  and wait up to one acquisition cycle for the socket to open.

---

## Verification

- Unit: `backend/tests/unit/onyx/onyxbot/`.
- External dependency: `backend/tests/external_dependency_unit/slack_bot/`, and
  the budget order on every LLM entry point in
  `backend/tests/external_dependency_unit/server/`.
- Integration: `backend/tests/integration/tests/users/`, which covers Slack user
  deactivation.
- By hand, with a real Slack app: a tag in a public channel must cite only
  public documents, a DM must reach private ones, and a user who is not on the
  allowlist must get no answer.
