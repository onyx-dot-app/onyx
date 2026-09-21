# Discord Bot

> A `discord.py` client that answers messages in registered Discord servers. It is
> a separate implementation from the Slack bot, not a reuse of it, and it does not
> map a Discord user to an individual Onyx identity: every message in a tenant is
> answered as one shared service account.

**Domain:** integrations
**Edition:** CE
**Owns:**
`backend/onyx/onyxbot/discord/` (`client.py`, `handle_message.py`, `handle_commands.py`,
`cache.py`, `api_client.py`, `constants.py`, `exceptions.py`, `utils.py`),
`backend/onyx/db/discord_bot.py`, `backend/onyx/server/manage/discord_bot/`
(`api.py`, `models.py`, `utils.py`), `web/src/app/admin/discord-bot/`

---

## 1. What the user experiences

An admin configures a Discord bot token once per deployment (self-hosted) or gets
one managed by Onyx on Cloud, then creates a guild registration at
`/admin/discord-bot` (`web/src/app/admin/discord-bot/page.tsx`). This produces a
one-time registration key. A Discord server admin runs `!register <key>` in any
channel of their server, which links that Discord guild to the tenant
(`handle_commands.py:handle_registration_command`). The Onyx admin then enables
the guild and its channels at `/admin/discord-bot/[guild-id]`, choosing a default
persona per guild and optionally overriding it per channel
(`web/src/app/admin/discord-bot/[guild-id]/page.tsx`). In an enabled channel, the
bot answers when @mentioned, or always if `require_bot_invocation` is off, or
implicitly when a user replies to the bot or posts in a bot-owned thread
(`handle_message.py:check_implicit_invocation`). Answers can go inline, as a
reply, or into a dedicated thread depending on `thread_only_mode`.

---

## 2. Surfaces

| Surface | Where |
|---|---|
| `/admin/discord-bot` | `web/src/app/admin/discord-bot/page.tsx`, guild list and bot config card |
| `/admin/discord-bot/[guild-id]` | `web/src/app/admin/discord-bot/[guild-id]/page.tsx`, channel table and persona overrides |
| `GET/POST/DELETE /manage/admin/discord-bot/config` | `discord_bot/api.py`, self-hosted-only bot token management |
| `GET/POST/PATCH/DELETE /manage/admin/discord-bot/guilds` (and `/guilds/{id}`) | `discord_bot/api.py` |
| `GET/PATCH /manage/admin/discord-bot/guilds/{id}/channels` | `discord_bot/api.py` |
| `DELETE /manage/admin/discord-bot/service-api-key` | `discord_bot/api.py` |
| `!register <key>` Discord command | `handle_commands.py:handle_registration_command` |
| `!sync-channels` Discord command | `handle_commands.py:handle_sync_channels_command` |
| `DISCORD_BOT_TOKEN`, `DISCORD_BOT_INVOKE_CHAR` env vars | `backend/onyx/configs/app_configs.py:2192-2193` |

Bot config API access is refused with 403 on Cloud (`MULTI_TENANT`) or when
`DISCORD_BOT_TOKEN` is set, since both mean the token is managed outside the
admin panel (`discord_bot/api.py:_check_bot_config_api_access`).

---

## 3. Data model

`DiscordBotConfig` (`backend/onyx/db/models.py:4525`): one row per tenant, fixed
`id='SINGLETON'`, holds the encrypted bot token when not set via env var.

`DiscordGuildConfig` (`models.py:4545`): one row per Discord server. `guild_id` is
`NULL` until the `!register` command completes it; `registration_key` is the
one-time key embedding the tenant id (`discord_bot/utils.py:generate_discord_registration_key`).
Holds `default_persona_id` and `enabled`.

`DiscordChannelConfig` (`models.py:4585`): one row per channel, foreign-keyed to a
guild config with `ondelete="CASCADE"`. Holds `require_bot_invocation`,
`thread_only_mode`, `persona_override_id`, `enabled`, and Discord-derived
`channel_type`/`is_private` metadata.

The Discord service API key is a regular `ApiKey` row named
`DISCORD_SERVICE_API_KEY_NAME` (`configs/constants.py:96`), one per tenant,
created lazily by `db/discord_bot.py:get_or_create_discord_service_api_key`.

---

## 4. How it works

```
OnyxDiscordClient.on_message                                    client.py
  ├─ handle_registration_command / handle_sync_channels_command  handle_commands.py
  ├─ cache.get_tenant(guild_id) -> tenant_id                     cache.py
  ├─ cache.get_api_key(tenant_id) -> service API key             cache.py
  ├─ should_respond(message, tenant_id, bot_user)                handle_message.py
  │     -> loads DiscordGuildConfig + DiscordChannelConfig by Discord ids
  └─ process_chat_message(...)                                   handle_message.py
        ├─ builds thread/reply-chain context
        └─ OnyxAPIClient.send_chat_message(message, api_key, persona_id)  api_client.py
              -> POST {api_server}/chat/send-chat-message, Bearer <service API key>
```

1. `DiscordCacheManager` (`cache.py`) refreshes every `CACHE_REFRESH_INTERVAL`
   (60s, `constants.py`), loading every tenant's enabled guild ids and
   provisioning a service API key per tenant if one is missing.
2. `on_message` (`client.py:OnyxDiscordClient.on_message`) resolves the guild's
   tenant purely from this in-memory cache, not a per-request DB lookup.
3. `should_respond` (`handle_message.py:should_respond`) looks up the
   `DiscordGuildConfig` and `DiscordChannelConfig` for the message's guild and
   channel (threads resolve to their parent channel's config), then decides
   whether to respond and which `persona_id` to use: channel override, else
   guild default.
4. `process_chat_message` (`handle_message.py:process_chat_message`) builds
   conversation context from thread history or the reply chain
   (`_build_thread_context`, `_build_reply_chain_context`), then calls
   `OnyxAPIClient.send_chat_message` with the **tenant's shared service API
   key**, never anything derived from the Discord message author.
5. The API client authenticates as that key's own Onyx user (see §5) and sends a
   non-streaming `SendMessageRequest` with `origin=MessageOrigin.DISCORDBOT`
   to `/chat/send-chat-message` (`api_client.py:send_chat_message`).
6. The answer is formatted with citations and chunked to Discord's 2000-character
   limit before being sent (`handle_message.py:_split_message`, `send_response`).

---

## 5. Contracts and invariants

1. **No Discord user maps to an Onyx user.** Every message in a tenant's
   registered guilds is answered using one shared `DiscordBotConfig`-adjacent
   service API key, whose owning `User` row is a synthetic API-key user created
   by `insert_api_key` (`backend/onyx/db/api_key.py`), not the message author.
   Document-level ACL, group membership, and permission-synced access are all
   evaluated against that single service identity for every Discord user in the
   server. **This is the security-relevant fact**: a channel-scoped persona
   restricts which agent responds, but it does not scope which documents that
   persona's searches can see per-Discord-user, because there is no per-user
   identity to scope against.
2. **Rate limiting and usage are tenant-wide, not per-Discord-user.** Because
   every request authenticates as the same API-key user,
   `check_token_rate_limits`/`check_api_key_usage` on
   `chat_backend.py:handle_send_chat_message` throttle the whole guild together.
   Contrast [[slack-bot]], where each Slack sender is provisioned as their own
   Onyx user (`onyx/db/users.py:add_slack_user_if_not_exists`), so rate limits
   and document ACLs apply per person. See [[rate-and-usage-limits]].
3. **`origin=MessageOrigin.DISCORDBOT` never survives API-key auth.**
   `chat_backend.py:handle_send_chat_message` overrides `origin` to
   `MessageOrigin.API` whenever the request carries a hashed API key or PAT
   (`chat_backend.py:836-839`), which every Discord bot request does. The
   `DISCORDBOT` enum value is set client-side but is unobservable server-side.
4. **A registration key is single-use and tenant-bound.** `register_guild`
   requires the guild's `guild_id` to still be `NULL`
   (`handle_commands.py:_register_guild`); a second `!register` with the same
   key is refused. One Discord guild can only ever map to one tenant
   (`cache.py:DiscordCacheManager` keys `_guild_tenants` by `guild_id`).
5. **New channels are disabled by default.** `create_channel_config` and
   `bulk_create_channel_configs` (`db/discord_bot.py`) never set `enabled=True`;
   an admin must opt a channel in explicitly after `!sync-channels` or initial
   registration.
6. **Deleting all guild configs on Cloud deletes the service API key.**
   `discord_bot/api.py:delete_guild_request` checks `MULTI_TENANT` and calls
   `delete_discord_service_api_key` once no guilds remain, which also deletes
   the key's synthetic user (`db/discord_bot.py:delete_discord_service_api_key`).

---

## 6. Relationships

**Depends on**
- [[core-chat-loop]]: every Discord answer is one `/chat/send-chat-message` call
  (`api_client.py:send_chat_message`); the Discord bot does not touch the loop
  internals directly.
- [[access-control]]: document visibility for every Discord answer is whatever
  the service API key's synthetic user can see, not the Discord author's
  permissions; see §5.1.
- [[agents-personas]]: `default_persona_id` / `persona_override_id` select the
  persona; there is no per-user persona choice.
- [[editions-and-gating]]: bot config API access is refused outright on Cloud
  (`_check_bot_config_api_access`), where the bot token is managed externally.

**Depended on by**
- Nothing in the codebase reads Discord-specific state back out; it is a
  terminal integration.

**Compare to** [[slack-bot]]: the Slack bot resolves a real Onyx user per Slack
sender via email (`add_slack_user_if_not_exists`, `get_user_by_email`) and
evaluates per-channel standard answers (see [[standard-answers]]) before falling
back to the LLM. Discord has neither: no per-user identity, and no standard-answer
integration in `handle_message.py`.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new field to `DiscordChannelConfig` or `DiscordGuildConfig` | the corresponding Pydantic model in `server/manage/discord_bot/models.py` and the admin frontend forms in `web/src/app/admin/discord-bot/` |
| changes how `should_respond` resolves persona or mention rules | `backend/tests/unit/onyx/onyxbot/discord/test_should_respond.py` |
| changes the service API key lifecycle | `backend/tests/integration/tests/discord_bot/test_discord_bot_api.py`, `test_discord_bot_db.py`; whether Cloud's guild-delete-deletes-key invariant (§5.6) still holds |
| adds any per-Discord-user identity resolution | re-verify §5.1 and §5.2 top to bottom; this changes the document's central security claim |
| changes registration key format or parsing | `discord_bot/utils.py:parse_discord_registration_key`, `backend/tests/integration/multitenant_tests/discord_bot/test_discord_bot_multitenant.py` |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/onyx/onyxbot/discord/
cd backend && uv run pytest tests/integration/tests/discord_bot/
cd backend && uv run pytest tests/integration/multitenant_tests/discord_bot/
cd backend && uv run pytest tests/external_dependency_unit/discord_bot/
```

Playwright coverage exists at `web/tests/e2e/admin/discord-bot/` (`bot-config.spec.ts`,
`guilds-list.spec.ts`, `channel-config.spec.ts`, `admin-workflows.spec.ts`); it
covers the admin panel, not live Discord message handling (the bot client itself
has no e2e coverage since it requires a live Discord connection).

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Set `DISCORD_BOT_TOKEN` or create a bot config via `/admin/discord-bot`.
3. Create a guild registration, run `!register <key>` in the target Discord
   server, then enable the guild and at least one channel.
4. @mention the bot in an enabled channel and confirm a response with citations.
5. Grep `backend/log/api_server_debug.log` for `discordbot` or the tenant id to
   confirm the request authenticated with the service API key.

### What "working" looks like

- A registered, enabled channel responds to mentions (or all messages, if
  `require_bot_invocation` is off) with a chunked, citation-annotated answer.
- A disabled channel or unregistered guild never responds.
- The service API key is created once per tenant and reused, not regenerated on
  every message.

---

## 9. Footguns

- **The persona is per-channel, not per-user.** Two different Discord members in
  the same channel always get answers from the same persona and the same
  document-access scope. There is no way, today, to give one Discord user
  broader document access than another within a channel.
- **`MessageOrigin.DISCORDBOT` is effectively dead on the server side.** It gets
  overwritten to `MessageOrigin.API` before any handler sees it (§5.3); do not
  rely on it for telemetry or behavior branching in `chat_backend.py`.
- **The cache, not the database, is the source of truth for routing at message
  time.** A guild enabled in the database will not answer until
  `DiscordCacheManager.refresh_all` or `refresh_guild` picks it up; registration
  calls `refresh_guild` immediately, but toggling `enabled` via the admin API
  does not proactively refresh the bot's cache; it waits for the next periodic
  refresh (up to 60s).
- **DMs are explicitly unsupported.** `handle_commands.py:handle_dm` always
  replies that it cannot respond in DMs and points to the public Onyx Discord.
- **`!sync-channels` only adds/removes/renames; it never re-enables anything.**
  Newly discovered channels are always created disabled
  (`db/discord_bot.py:sync_channel_configs`).

---

Cross-links: [[slack-bot]], [[core-chat-loop]], [[access-control]],
[[editions-and-gating]], [[rate-and-usage-limits]], [[agents-personas]],
[[chat-persistence]]
