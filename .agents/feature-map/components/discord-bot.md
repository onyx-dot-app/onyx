# Discord Bot

> A `discord.py` client that answers messages in registered Discord servers by
> calling the public chat API over HTTP. It uses one service API key per tenant,
> so every Discord member in a tenant is answered as the same Onyx identity.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE. On cloud, Onyx manages the bot token.

---

## User experience

- **An Onyx admin** with the manage-bots permission sets the bot token on the
  Discord Bot admin page. Only self-hosted admins can, because cloud and the
  `DISCORD_BOT_TOKEN` env var manage the token elsewhere. The admin creates a
  server registration and gets a one-time key. The customer guide is
  `documentation/admins/miscellaneous/discord_bot.mdx`.
- **A Discord server admin** (Administrator or Manage Server) runs
  `!register <key>` in any channel. The bot links the server to the tenant and
  lists its text and forum channels. A failed registration is reported by DM
  and the command message is deleted.
- **The Onyx admin then enables channels.** A registered server is on, but
  every channel starts off. The admin picks a default agent for the server and
  can override it per channel. `!sync-channels` adds new channels (off) and
  removes deleted ones.
- **A Discord member** in an enabled channel @mentions the bot, replies to the
  bot, or posts in a thread the bot started. A channel can also answer every
  message. The bot reacts while it works, then replies with the answer and up
  to five sources, split into 2000-character messages. In thread-only mode it
  answers in a new thread.
- **Every member gets the same document access.** Answers use the service
  account's access, not the member's. A DM to the bot gets a fixed "I can't
  respond to DMs" reply. A failed answer gets an apology in a thread.

---

## Scope

This component owns the bot process, its guild-to-tenant cache, the
registration and sync commands, the guild and channel config records with their
admin API and admin pages, and the per-tenant service API key that the bot
creates.

Its neighbours own:
- [[onyx-api]]: the chat route the bot calls.
- [[core-chat-loop]]: the turn behind that route.
- [[auth-and-identity]]: API-key authentication.
- [[rate-and-usage-limits]]: budgets and the API-call cap.
- CROSS-CUTTING.md: the acting-user rules for Discord and the other surfaces.

The Discord bot has no standard answers ([[standard-answers]] is Slack only).
The Discord connector is a separate feature that indexes Discord messages.

---

## Architecture

```
client.py:OnyxDiscordClient.on_message
  ignore bots and DMs (handle_dm)
  handle_registration_command / handle_sync_channels_command
  cache.get_tenant(guild_id) -> tenant_id              in-memory, refreshed every 60 s
  cache.get_api_key(tenant_id) -> raw service key
  should_respond                                       reads guild + channel config from the DB;
                                                       threads use the parent channel's config
  process_chat_message
    thread history or reply chain -> one message text
    OnyxAPIClient.send_chat_message                    POST /chat/send-chat-message,
                                                       Bearer <service key>, stream=False
    _append_citations, send_response
```

**One client, many tenants.** One process serves every tenant.
`onyxbot/discord/cache.py:DiscordCacheManager` maps each enabled, registered
guild to its tenant, and each tenant to its service API key. The registration
key carries the tenant id (`parse_discord_registration_key`), which is how
`!register` finds the tenant before any cache entry exists.
`backend/onyx/onyxbot/discord/DISCORD_MULTITENANT_README.md` explains the
design.

**The service API key.** `db/discord_bot.py:get_or_create_discord_service_api_key`
creates an `ApiKey` named `DISCORD_SERVICE_API_KEY_NAME`. The database keeps
only the hash, so when the cache has no raw key the function regenerates the
key and overwrites the stored hash.

**Context.** The bot puts up to `MAX_CONTEXT_MESSAGES` earlier messages and the
author's display name into the message text itself. Each Discord message
starts a new chat session, so the API sees no history.

---

## Contracts and traps

1. `single-bot-process` **Run exactly one bot process.** The Helm template
   (`deployment/helm/charts/onyx/templates/discordbot.yaml`) pins
   `replicas: 1`. A second process starts with an empty cache, so it
   regenerates each tenant's service key. The first process keeps its cached
   key and gets 401s until its next restart.
2. `no-member-identity` **No Discord member maps to an Onyx user.** Document
   ACLs, groups and budgets all apply to the service key's user. A channel
   agent chooses which agent answers. It does not limit which documents each
   member can reach. Enabling a private Discord channel does not make its
   answers private to its members.
3. `tenant-shared-budget` **Budgets throttle the whole tenant together.** Every
   request carries the same key, so `check_token_rate_limits` and
   `check_api_key_usage` on
   `server/query_and_chat/chat_backend.py:handle_send_chat_message` count all
   guilds as one caller. Per-user and per-group budgets do not apply to API-key
   users ([[rate-and-usage-limits#shared-principals-global-only]]).
4. `discordbot-origin-overwritten` **`MessageOrigin.DISCORDBOT` does not reach
   the server.** `handle_send_chat_message` sets the origin to
   `MessageOrigin.API` for any request with an API key or PAT. Do not branch on
   `DISCORDBOT` server-side.
5. `routing-depends-on-cache` **Routing depends on the cache.**
   `onyxbot/discord/client.py:OnyxDiscordClient.on_message` finds the tenant
   only in `DiscordCacheManager`, which holds enabled guilds of
   tenants that are not gated
   (`onyxbot/discord/cache.py:DiscordCacheManager.refresh_all`). A gated
   tenant's guilds get no reply. Registration calls `refresh_guild` at once.
   Enabling a guild through the admin API waits for the next refresh. Disabling
   takes effect at once, because
   `onyxbot/discord/handle_message.py:should_respond` reads `enabled` from the
   database on each message.
6. `registration-key-single-use` **A registration key is single-use, and a
   guild maps to one tenant only through the cache.**
   `onyxbot/discord/handle_commands.py:_register_guild` refuses
   a key whose `guild_id` is set, and a guild that the cache already maps. Each
   tenant has its own `DiscordGuildConfig` table, so no database constraint
   stops two tenants from registering one guild while the cache does not hold
   it, for example when the guild is disabled.
7. `channels-start-disabled` **New channels start disabled, and sync never
   enables.** `db/discord_bot.py:create_channel_config`,
   `bulk_create_channel_configs` and `sync_channel_configs` rely on the `enabled` server default of false.
8. `cloud-last-guild-deletes-key` **On cloud, deleting the last guild deletes
   the service key and its user.**
   `server/manage/discord_bot/api.py:delete_guild_request` calls
   `delete_discord_service_api_key` when no guilds remain.
9. `cached-key-trusted` **The bot never checks its cached key against the
   database.** `DiscordCacheManager._load_tenant_data` returns the cached raw
   key whenever one exists, and creates a key only when the cache has none. A
   key deleted or replaced outside this process
   (`server/manage/discord_bot/api.py:delete_service_api_key_endpoint`,
   `delete_bot_config_endpoint`, a second process, or a cloud guild deletion
   followed by a new registration before the next refresh) gives 401s until
   the bot restarts or the tenant has no enabled guild at a refresh.

---

## Known issues

- **A bot token change needs a process restart.**
  `onyxbot/discord/client.py:main` reads the token with
  `onyxbot/discord/utils.py:get_bot_token` once, before `bot.run`. It does not
  poll for a new token while the bot runs.
- **The whole thread is sent as one user message.** Context is pasted into the
  message text, so it is saved in chat history and counts against token
  budgets on each turn.

---

## Dependencies

- [[onyx-api]]: the bot is a client of `POST /chat/send-chat-message`.
- [[core-chat-loop]]: runs each answer.
- [[access-control]]: document scope is the service key user's scope.
- [[agents-personas]]: the guild default and the channel override select the agent.
- [[multi-tenancy]]: the cache maps guilds to tenants and sets the tenant context for each load.
- [[auth-and-identity]]: the service API key and its user.
- [[fleet-telemetry]]: Discord queries report channel `api`
  ([[fleet-telemetry#discord-reports-api-channel]]).

---

## Recipes

- `run-bot-locally` **Run the bot locally.** Use the "Discord Bot" entry in
  `.vscode/launch.json`, or run `onyx/onyxbot/discord/client.py` from
  `backend/`. Set the token on the admin page or in `DISCORD_BOT_TOKEN`; with
  no token the process waits and polls. Create a registration on the admin
  page, run `!register <key>` in a test server, then enable one channel.
- `investigate-no-reply` **Investigate "the bot does not reply".** Read the `discord_bot` process log.
  A DM always gets the fixed reply. In a server, check in order: the guild is
  in the cache ([[#routing-depends-on-cache]]; wait one refresh after an admin
  enable), the tenant has a cached API key (a "No API key cached" warning), the
  channel is enabled ([[#channels-start-disabled]]; threads use the parent
  channel), and the message mentions the bot or replies to it when the channel
  requires an invocation. A run of 401s after a deploy means two bot processes
  ([[#single-bot-process]]). A run of 401s after an admin deleted the service
  key needs a bot restart ([[#cached-key-trusted]]).

---

## Verification

- Unit: `backend/tests/unit/onyx/onyxbot/discord/`.
- External dependency: `backend/tests/external_dependency_unit/discord_bot/`.
- Integration: `backend/tests/integration/tests/discord_bot/` and
  `backend/tests/integration/multitenant_tests/discord_bot/`.
- Playwright covers the admin pages only: `web/tests/e2e/admin/discord-bot/`.
  Message handling needs a live Discord server: register, enable one channel,
  mention the bot, and confirm a cited answer.
