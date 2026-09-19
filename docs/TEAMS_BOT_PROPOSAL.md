# TeamsBot: feature parity and implementation proposal

Status: proposed; no TeamsBot application code is included in this change.
Research date: 2026-09-19.
Onyx baseline: `711a0479f1630dcce38f8f58212a63080702b753` on upstream `main`.

## Recommendation

Add a Python Teams adapter over Onyx's existing chat and retrieval pipeline.
Use the Microsoft 365 Agents SDK for authenticated Teams transport.
Use Slack's distinction between private answers and shared answers as the access-control baseline.
Use Discord's explicit channel enablement and agent override model for administration.

The first release should support personal chat and approved standard channels.
Group chat, targeted private replies, feedback, and the remaining Slack controls follow in separately tested changes.
The first release is **core parity**, not full parity.
The matrix below defines the complete target and the remaining differences.

This is a medium integration project, not a small transport rename.
Identity, audience safety, durable delivery, and Teams consent are the main work.
No new retrieval engine, model provider, or Teams indexing connector is required.

## Evidence and research limits

The local repository, official GitHub repository, and public Onyx documentation were accessible.
I inspected bot listeners, handlers, renderers, database models, admin APIs, configuration UI, and relevant tests.
The [Slack setup guide][O1] and [Discord setup guide][O2] supplement the code findings below.
Code is the baseline where documentation and implementation differ.

Onyx already has a [Teams indexing connector][O3] and Enterprise permission synchronization.
These ingest messages and files; they do not provide a conversational Teams bot.
The current bot directories contain only `slack/` and `discord/`. [S1], [D1], [T1]

Existing demand and prior work:

- [Issue #4115](https://github.com/onyx-dot-app/onyx/issues/4115) requests Slack-like functionality after a Teams migration.
- [Issue #4684](https://github.com/onyx-dot-app/onyx/issues/4684) requests Teams assistant integration and setup instructions.
- [PR #4357](https://github.com/onyx-dot-app/onyx/pull/4357) is closed and unmerged. Its discussion includes continued user interest.
- [PR #8923](https://github.com/onyx-dot-app/onyx/pull/8923) is closed and unmerged. It proposed Bot Framework v4 and shared Discord utilities.
  Its automated reviews raised identity-routing, invoke-response, registration-race, and API-key-rotation concerns.
  Those reviews are prior-review evidence, not proof of defects in today's `main`.
- Searches for Teams bot work and open Teams titles found connector work, including [#14856](https://github.com/onyx-dot-app/onyx/pull/14856) and [#14863](https://github.com/onyx-dot-app/onyx/pull/14863).
  No open TeamsBot implementation appeared in those searches. Unpublished work remains unknown.

No Microsoft tenant, Azure bot, or live Slack/Discord deployment was tested for this proposal.
Platform behavior below comes from official documentation; SDK integration and client compatibility require the first implementation phase.
Several Microsoft pages display an authorization banner but still expose their article text. The cited text was readable.
Microsoft's private/shared-channel pages differ in scope and wording; installation support does not establish conversational support.
No maintainer approval or acceptance is implied.

## Verified bot behavior

### Slack

`SlackbotHandler` maintains tenant-specific Socket Mode clients, with Redis ownership locks and heartbeat handling.
Bots have encrypted app, bot, and optional user tokens, an enabled flag, and default/channel configurations.
Management routes require `Permission.MANAGE_BOTS`. [S1], [S6], [S7]

Events are acknowledged promptly. The listener accepts mentions, supported new messages, and slash commands.
It suppresses self-messages, duplicate mention delivery, unsupported message subtypes, and empty text.
Unmentioned non-root channel replies are skipped; bot DMs and explicit mentions can continue a thread.
Other bots can trigger answers when configured or explicitly mentioning Onyx. [S1]

The handler resolves Slack email through Slack's user information API.
Provisioning applies invite, allowed-domain, license-seat, and account-type checks.
An invocation allowlist is resolved before account provisioning.
It can also scope response delivery to specified users or Slack groups. [S3]

Regular answers use `handle_stream_message_objects` followed by `gather_stream`.
They create a new chat session for the turn and pass fetched Slack thread text as additional context.
The channel persona supplies document sets and tools. Search is forced initially only when configured, enabled, and available.
Channel mentions can become indexed-search channel filters. Slack context also reaches federated Slack search. [S2], [S8]

The requester must be able to read the configured persona.
Private bot DMs and configured ephemeral responses use the mapped user's retrieval access.
Ordinary shared responses use `get_anonymous_user()` and `bypass_acl=False`, limiting indexed retrieval to public documents.
Usage attribution can use a different user from retrieval authorization. [S2], [A1]

Answers are assembled before sending, rather than streamed into Slack.
Blocks contain formatted answer text, citation sources, and configurable actions.
The code supports helpfulness feedback, reminders, human escalation/resolution, private-answer publication, and web continuation.
Enterprise Standard Answers can precede generation and expose a Generate Full Answer button. [S4], [S5], [E1]

### Discord

`OnyxDiscordClient` uses `discord.py` Gateway events and enables message-content and member intents.
A cache maps guild IDs to Onyx tenants and tenant service API keys; it refreshes every 60 seconds.
Cloud reads a bot token from the environment. Self-hosted installations can use an encrypted database token.
Admin APIs require `MANAGE_BOTS`. [D1], [D3], [D4], [D5]

Onyx issues a registration key; a Discord administrator or Manage Server member runs `!register`.
`!sync-channels` refreshes text/forum channels. Newly discovered channels are disabled by default.
Guild defaults and channel agent overrides determine the persona.
Mention-only mode also accepts replies to bot messages and messages in bot-owned or bot-started threads. [D2], [D4], [D6]

DMs receive an unsupported-DM message, not an answer.
All bot-authored messages are ignored.
Thread/reply history is converted into text with readable mentions and a forum title when applicable.
The configured context limit is 10 messages; starter-message insertion means it is not a strict bound in every branch. [D1], [D2]

Each turn calls `/chat/send-chat-message` with `stream=False`, a new session, and `origin=DISCORDBOT`.
The bearer token represents a tenant service account, not the Discord member.
There is no Discord-user-to-Onyx-user mapping in this path.
Normal Onyx authorization applies to that service account; it is not a blanket ACL bypass.
Its effective access must not be mistaken for the access of every channel member. [D3], [D7], [A2]

The response appends up to five source entries, sorted by citation number, and splits text at 2,000 characters.
It replies inline, sends into an existing thread, or creates a thread according to configuration.
It adds/removes a thinking reaction and sends a generic error on failure.
The HTTP client has a 180-second timeout and typed connection, timeout, and response errors. [D2], [D3]

## Feature-parity matrix

“Absent” means absent from the inspected bot path, not absent from Onyx's web application.
P1–P6 refer to the implementation phases below. Platform-dependent items require tenant/client validation.

| Capability | SlackBot today | DiscordBot today | Proposed TeamsBot equivalent | Teams limitation or parity decision |
| --- | --- | --- | --- | --- |
| Bot administration | Multiple bots; default and channel settings; encrypted tokens [S6], [S7] | Token config; guild/channel settings; Cloud env token [D4], [D5] | P1: bot registration and explicit destination configuration; `MANAGE_BOTS` | Azure/Entra and Teams installation are separate from Onyx configuration |
| Agent and knowledge selection | Agent or document-set persona; channel override [S2], [S6] | Guild agent, channel override [D2] | P1–P2: default agent and team/channel/chat overrides | Agent visibility and document access are separate checks |
| Personal conversations | Supported, including private indexed knowledge [S2] | DMs explicitly rejected [D6] | P2: personal bot chat with verified user mapping | Installation and account linking required |
| Shared channels | Mentions or configured automatic root replies [S1] | Enabled text/forum channels [D2], [D6] | P2: standard Teams channel posts and thread replies | Private/shared Teams channel support is a separate platform gate [M4], [M5] |
| Group conversations | Multi-person events can be handled; only `im` is treated as bot DM [S1] | Guild channels; no group-DM answer path [D1] | P3: approved group chats with shared-answer policy | Group chat is not a private answer for the requester |
| Explicit invocation | Mention and `/onyx` [S1] | Mention; command prefix is for setup commands [D1], [D6] | P2 mentions; P4 targeted slash entry where supported | Teams targeted commands differ from Slack slash webhooks [M6] |
| Automatic replies | Configurable, with pre/post filters [S3] | All messages in enabled channels when invocation is not required [D2] | P3: opt-in RSC receive-all mode plus channel rules | Requires consent for `ChannelMessage.Read.Group` or `ChatMessage.Read.Chat` [M3] |
| Follow-up triggers | Re-mention in channel threads; bot-DM thread replies [S1] | Reply-to-bot and bot-owned/started-thread exceptions [D2] | P2 re-mention; P3 implicit follow-up when receive-all is authorized | A reply alone does not normally deliver an activity to the bot [M4] |
| Conversation context | Fetches Slack thread, then supplies additional context [S1], [S2] | Rebuilds thread/reply-chain text for each new session [D2], [D3] | P2 stores observed turns; P3 authorized history lookup | Mention-only delivery omits other messages; never claim complete context without history permission |
| Retrieval and persona tools | Normal Onyx pipeline; conditional forced search; Slack-aware filters [S2], [S8] | Normal Onyx chat API; no bot-specific forced-search logic [D3] | P2 existing pipeline with Slack-like grounding when search is available | Shared-mode tools need an audience-safe policy; tool artifacts are not automatically chat-compatible |
| Indexed Teams knowledge | Available through normal retrieval if configured [T1] | Same normal retrieval path | Reuse Teams connector and its existing permission sync | Bot installation does not configure indexing or grant Graph indexing rights |
| Live workspace search | Slack federated search receives Slack event context [S8] | No Discord-specific live-search adapter in bot path | Existing Onyx search sources remain available to permitted users | A new federated Teams search adapter is a separate feature, not achieved by adding TeamsBot |
| Citations | Numbered source blocks, titles, links, source metadata [S4] | Up to five numbered source entries [D2] | P2 numbered sources and links in answer/cards; preserve citation mapping | Split by encoded payload size; do not expose uncited or unauthorized metadata |
| Response formatting | Slack Markdown conversion, 3,000-character sections, 50-block final cap [S2], [S4] | Markdown text split at 2,000 characters [D2] | P2 Teams-compatible text and Adaptive Cards | Approximate message limit is 100 KB; Microsoft recommends 80 KB. Extended Markdown is preview [M7] |
| Streaming/status | Gathered final answer; reaction/acknowledgment [S2], [S3] | Final answer; thinking reaction [D2] | P2 typing/status followed by final answer | Token streaming is not needed for parity; targeted messages do not support reactions [M6] |
| Inbound files/images | `file_share` text accepted, but `file_descriptors=[]`; no attachment-content ingestion [S1], [S2] | No attachment processing in message path [D2] | Explicit unsupported-file notice; text still works | File ingestion is beyond current parity. Teams file consent APIs are personal-scope only; Graph differs [M8] |
| Answer feedback | Helpful/Not helpful; private/anonymous/public confirmations [S4], [S5] | Absent | P4 Adaptive Card actions backed by existing feedback data | Validate clicker, tenant, answer, and action expiry; return proper invoke response |
| Source feedback | Legacy action/modal handlers exist; normal response renderer does not emit the source-feedback button [S4], [S5] | Absent | No new source-rating UX required for the baseline | Treat dormant handlers as legacy, not a currently exposed feature |
| Private in-channel answer | Ephemeral response, including `/onyx` [S2] | Absent | P4 targeted answer where supported; otherwise personal-chat handoff | Targeted messages expire after 24 hours; failures must never fall back to public delivery [M6], [M9] |
| Share private answer | Share with Everyone reposts the saved answer [S5] | Absent | P4 share only content authorized for the destination | Consent alone does not make private documents public; use a fresh approved public prompt or keep private |
| Continue in Onyx | Configurable link plus Slack-specific session seeding [S4], [A3] | Absent | P4 authenticated continuation for a verified owner | Generalize the handoff safely; do not create public session links |
| Human follow-up | Optional escalation tags, resolved action, reminder [S3], [S4], [S5] | Absent | P5 card-based escalation and resolution; scheduled reminders | Resolve configured Entra users; team-tag mentions require separate capability/permission validation |
| Question/citation filters | Question-mark prefilter and citation postfilter; explicit mentions bypass content filters [S2], [S3] | No equivalent filters | P3 same configurable policy and bypass semantics | Allowlist, tenant, and permission gates are never bypassed |
| User/group invocation allowlist | Emails/Slack groups; also scopes response visibility [S3] | No equivalent; server/channel gates only | P3 Onyx-user/group allowlist; P4 individually private delivery | Do not equate Slack user groups with Teams teams or tags |
| Other bots | Conditional opt-in; never self [S1] | All bot authors ignored [D1] | Ignore by default; P5 evaluate authenticated bot actors | Teams activity delivery may differ; do not promise a bot-to-bot transport equivalent |
| Standard Answers | Enterprise-only category matching and Generate Full Answer [E1] | Absent | P5 reuse EE matching and render Teams cards | Preserve CE/EE boundaries; no duplicated matcher |
| Tenant/license/usage gates | Per-event product gate, seat/provisioning checks, usage attribution [S1], [S3] | Gated tenants omitted from cache; service account API call [D4] | P1–P2 per-turn gate, normal spend/model checks, mapped-user attribution | Never use a service identity to bypass seats or disabled users |
| Retries and errors | Generation retries; Slack SDK retry; optional error/no-answer messages; configurable rate limits [S1], [S2] | Generic errors, 180-second API timeout, SDK transport behavior [D2], [D3] | P2 bounded delivery retries, deduplication, safe error text and status cleanup | Honor `Retry-After`; do not retry every error or regenerate answers after delivery failure [M10] |

Additional code/documentation differences matter:
Slack's automatic-filter display code is commented out; a stored `enable_auto_filters` flag is not proof of an active feature.
Its source renderer declares a five-document setting but does not increment its local inclusion counter.
Do not promise a verified five-source cap for Slack based on that setting alone. [S4]
Discord's docs describe setup commands inconsistently; the code implements both `register` and `sync-channels`. [D6], [O2]

## Teams user experience

In personal chat, users link their Onyx account once, then send normal questions.
Answers use their selected/default agent and current Onyx access.
Unknown, inactive, unlicensed, or unlinked identities receive setup or access guidance without restricted content.
The bot does not silently fall back to a broadly privileged service account.

In an approved standard channel, `@Onyx What is the deployment process?` produces an answer in the same thread.
The default is mention-only. Administrator-enabled receive-all mode may answer root questions automatically.
Follow-ups use the same destination configuration; they must not switch to a featured/global agent.
Group chats follow the same shared-answer rules, using a configured chat agent or the bot default.
There is no assumption that a group chat or personal chat has a team ID.

Use a bounded context window and a token budget.
Initial context contains only activities the bot actually received and previously authorized responses.
If a user asks about unseen history, explain the limit or request a quoted message.
P3 can fetch earlier messages through consented Graph v1.0 APIs for that exact conversation.
Never substitute an entire team, channel, or tenant transcript for the referenced thread. [M11], [M12]

Private requests use personal chat first, then targeted messaging when validated.
Keep private histories separate even when requests occur inside a shared conversation.
Sharing must not expose the original private prompt through Teams Prompt Preview. [M6]

## Current Microsoft platform choices

Use **Microsoft 365 Agents SDK for Python**, with hosting-core, FastAPI hosting, MSAL authentication, and Teams hosting as needed.
The official Python repository lists these packages and supports Python 3.13.
Pin compatible released versions after a dependency and authentication spike; no package versions were installed or validated here. [M1]

Do not introduce `botbuilder-core`/`BotFrameworkAdapter` for a new contribution.
Microsoft archived the Bot Framework SDK; support ended in December 2025. [M2]
Teams SDK for Python is also generally available; the current reference lists version 2.1.0, released September 16, 2026. [M13], [M22]
Agents SDK is the provisional choice because its explicit FastAPI hosting fits Onyx's backend.
P0 must compare authentication, worker continuation, and targeted-message support with the current Teams SDK before the final choice.
Use the SDK for transport/authentication, not another LLM orchestration layer.

The current targeted-message documentation supports private, single-recipient exchanges inside group conversations.
Receiving them requires `supportsTargetedMessages`; users can enter through an agent slash command.
They expire after 24 hours and cannot change visibility in place.
The implementation must test the selected Python SDK, manifest, tenant rollout, and clients before declaring parity. [M6]

Private/shared channels remain a conditional extension.
The current channel-conversation guide explicitly says agents cannot post messages or Adaptive Cards in private channel conversations.
Other Microsoft pages describe newer app installation support and `supportsChannelFeatures`.
These statements do not justify promising universal bot conversation support.
Exclude private/shared channels from the initial supported matrix; require a real-tenant capability test before enabling either. [M4], [M5]

### Administrator setup and permissions

1. An Onyx administrator creates a Teams bot configuration with `MANAGE_BOTS`.
2. An Entra administrator creates the bot's application identity and records its application and directory tenant IDs.
3. Provision the Azure Bot resource and enable its Microsoft Teams channel.
4. Configure the bot identity using the current Agents SDK connection settings.
5. Set the messaging endpoint to the deployment's public HTTPS Teams callback route.
6. Upload an app package containing the manifest and icons through the permitted organizational app process.
7. Install it in personal scope and approved teams/chats. Configure destinations and agents in Onyx.
8. Complete account linking and test a public document, a private document, and an unauthorized user.

New deployments should use the documented single-tenant identity path or an appropriate managed identity.
Microsoft deprecates creation of new multi-tenant Azure Bot resources after July 31, 2025.
SDK support for legacy multi-tenant credentials does not mean a new cross-tenant SaaS registration can be assumed.
For Onyx Cloud, start with customer-owned bot registrations routed to the correct Onyx tenant.
A centrally published cross-tenant Onyx app requires a separate Microsoft deployment review. [M14]

For local testing, a short-lived client secret can be used where tenant policy allows it.
Prefer managed identity, federated credentials, or a supported certificate configuration in production.
The feasible option depends on hosting and the selected Python authentication package.
Store any secret/certificate material using Onyx encrypted credential patterns, with explicit rotation and expiry checks.
Current Microsoft provisioning guidance recommends federated credentials for Teams agents that need SSO. [M15], [M16]

The app manifest uses `personal`, `team`, and `groupChat` bot scopes as implemented.
Include the bot ID, required app metadata/icons, approved domains, and only supported capabilities.
Do not set `supportsFiles` while attachment content is unsupported.
Validate against a pinned current manifest schema. [M17], [M18]

| Permission or credential | Needed for | Initial policy |
| --- | --- | --- |
| Bot application identity and Azure Bot channel | Authenticate incoming activities and outgoing bot replies | Required; not an end-user Onyx identity |
| Teams app installation and organization policy | Allow users to use the bot in a scope | Required for each supported scope |
| `ChannelMessage.Read.Group` RSC | Receive unmentioned messages in an installed team | Optional P3; explicit resource-owner consent and tenant policy |
| `ChatMessage.Read.Chat` RSC | Receive unmentioned messages in an installed chat | Optional P3; separate consent |
| Graph history reads | Recover earlier channel/chat context | Optional P3; use resource-scoped permissions when supported by the endpoint |
| Entra user SSO / Onyx linking | Bind the Teams actor to an Onyx user | Required before private retrieval; not implied by bot authentication |
| Connector Graph permissions | Index Teams/SharePoint content | Existing connector's separate setup; not needed merely to converse |
| Broad Graph directory or message permissions | Tenant-wide discovery, indexing, or unrelated automation | Do not request for the core bot |

RSC receive-all consent and Graph history access are related but separate operations; test both paths independently. [M3], [M11], [M12]
Use bot conversation APIs for normal replies. Do not use Graph message-import permissions to send conversational answers.
An installed bot can access conversation metadata through its bot APIs, avoiding broad directory discovery for basic configuration. [M4]

Native bot SSO is documented for personal and group-chat scope, not channel scope.
For SSO, configure the Entra exposed API/scope, permitted Teams clients, OAuth connection, and manifest `webApplicationInfo`.
Validate audience, issuer, tenant, subject, nonce/state, and token-exchange binding.
For channel users, offer personal-chat or authenticated Onyx account linking rather than assuming silent channel SSO. [M19], [M20]

Host the callback behind the existing HTTPS ingress, or a dedicated route to the same backend image.
Configure Azure Bot's messaging endpoint to match that route; Azure hosting itself is not a prerequisite for self-hosted Onyx.
The deployment needs outbound access to Microsoft identity and bot endpoints.
Local testing uses a controlled HTTPS tunnel and a non-production Teams application. [M18]

## Architecture and access controls

### Request flow

1. The SDK validates the callback JWT before the activity reaches application handlers.
2. Resolve the registered bot identity and verified Entra tenant to an Onyx tenant.
3. Check installation, destination enablement, actor identity, permissions, and product/license gates.
4. Persist a deduplicated inbound event and its authorized delivery context, then acknowledge receipt.
5. A bounded worker resolves context and calls the existing Onyx answer pipeline with explicit retrieval access.
6. Persist the answer and authorized citation metadata, then send or update the Teams response.
7. Record delivery IDs and action references for retries, feedback, and continuation.

The synchronous message-generation path should stay synchronous.
Confine required async code to the Microsoft SDK transport boundary.
Validate adapter lifecycle and outbound continuation from workers during P0; never retain an HTTP turn object for a later job.
Use existing Celery infrastructure with a dedicated queue/optional consumer for long bot answers.
Do not block the HTTP request while the LLM runs or occupy the indexing coordination queue.

### Identity and audience rules

There are three separate identities: the bot application, the human actor, and the retrieval principal.
The bot application only proves that traffic came through an authorized transport.
It must not select a tenant or impersonate a user using unchecked activity fields.

Persist a binding from `(Onyx tenant, Entra tenant ID, Entra object ID)` to an Onyx user.
Establish it through authenticated Onyx linking or verified SSO claims tied to the current Teams actor.
Prefer existing identity-provider mappings only when their immutable identifier semantics are verified.
Do not equate an OIDC subject with an Entra object ID, or trust typed email/display names as identity.
Handle guests, renamed emails, account deletion, and duplicate links explicitly.

For every turn, recheck active status, basic access, persona access, provider permissions, and applicable license/spend gates.
An Entra sign-in does not authorize automatic Onyx provisioning.
If just-in-time provisioning is later enabled, apply invite, domain, account-type, and seat rules before creating accounts.
Keep usage attribution to the actor while choosing the retrieval principal separately. [S2], [S3], [A1]

Personal and targeted answers use the linked user's normal Onyx ACLs, with `bypass_acl=False`.
Shared answers use the existing public-document retrieval principal and an approved shared-use agent.
Never use the union of channel members' groups or the requester's private access for a shared answer.
Document-set selection narrows retrieval but does not replace ACL checks. [A1], [A2]

Onyx-public means public within the Onyx deployment, not public on the internet.
Before shared mode is enabled, require explicit administrator approval of the destination and its eligible audience.
Default to internal, linked Onyx members; deny guest/federated or unverifiable audiences until a separate policy is approved.
Membership changes invalidate the cached audience decision; an unavailable roster check must fail closed.
Private/shared Teams channels are not shortcuts around these rules.

Public-document filtering alone cannot protect secrets in agent instructions, attached agent files, memory, or delegated tools.
Shared-use agents must have approved public inputs and tools; disable private memory and user-authenticated tool access in shared mode.
Evaluate tool results under the same audience policy as retrieved documents.
Existing Onyx controls remain authoritative; the Teams adapter must not add an impersonation endpoint.

Partition history by tenant, bot, conversation/thread, and visibility; private history also includes the recipient's immutable ID.
Never reuse a personal or targeted answer as context for a public response.
Recheck authorization before sending delayed answers, rendering citations, and handling card actions.
Permission revocation cannot retract content already read in Teams; document this delivery boundary.

The Share action must not simply repost Slack's saved private-answer payload.
Offer direct sharing only for an answer produced entirely from shared-safe inputs and sources.
Otherwise require a newly approved public question and a fresh public-access answer, or keep the result private.
Do not copy private Prompt Preview metadata to a public activity.
Normal web continuation must authenticate and authorize the owner; private sessions never receive public sharing links.

### Transport and delivery security

Use SDK JWT validation for signature, issuer, audience, expiry, and the configured bot connection.
Also authorize the Teams channel, installation, and tenant binding.
Apply Microsoft's service-URL validation and outbound host restrictions; they are not all enabled automatically.
Never send bot credentials to a service URL merely because it appeared in JSON. [M21]

Use a unique event key containing bot registration, verified tenant, conversation, activity ID, and event type/version.
Store a durable inbox/outbox record before acknowledging a message.
Return invoke-specific status and body for card/token-exchange activities instead of an unconditional HTTP 200.
Use per-thread ordering, bounded retries, task expiration, and short database transactions.
Onyx's Celery thread pools require explicit operation deadlines; Celery time-limit settings alone do not enforce them.

Persist generated answers separately from delivery attempts, so a network retry does not repeat a paid generation.
Retry known transient delivery failures with bounded backoff and jitter; honor Microsoft's `Retry-After` guidance. [M10]
Deduplicate repeated inbound events and recorded sends.
A crash between a remote send and local persistence creates an ambiguous outcome; record/reconcile it rather than claiming exactly-once delivery.
Remove stale typing/status indicators where possible and return a safe failure message.
Logs contain correlation IDs and safe error categories, not tokens, raw prompts, or retrieved secrets.

### Reuse and proposed file changes

| Area | Reuse | Proposed change |
| --- | --- | --- |
| Answer generation | `chat/process_message.py`, `SendMessageRequest`, `ChatBasicResponse`, persona/search models | Add a small `onyx/onyxbot/common/answer.py` service with explicit actor, retrieval principal, persona, and context |
| Message attribution | `server/query_and_chat/models.py:MessageOrigin`, existing usage/tracing | Add `TEAMSBOT`; retain normal spend checks and user attribution without a separate LLM call path |
| Slack integration | Existing generation behavior and usage attribution | Extract only the shared generation boundary in a separate regression-tested PR; keep Slack transport/renderers |
| Discord integration | Configuration semantics, history policy, API response models | Keep its Gateway and API client behavior; do not force it onto a new framework |
| Teams transport | Microsoft SDK auth/activities/continuation | Add `backend/onyx/onyxbot/teams/` with transport, handlers, context, rendering, and typed models |
| Callback and management | FastAPI router registration, `MANAGE_BOTS`, `OnyxError` | Add `server/manage/teams_bot/` and a separate SDK-authenticated callback router; register in `onyx/main.py` |
| Persistent configuration | Encrypted fields, tenant DB helpers, personas | Add `db/teams_bot.py`, models, and normal/tenant Alembic migrations |
| Delivery processing | Celery queues, tenant propagation, retry conventions | Add Teams tasks, durable event/delivery records, and an optional bot-answer consumer |
| Feedback and handoff | `db/feedback.py`, session authorization and duplication primitives | Add authorized Teams card handlers; generalize Slack-only web handoff only when needed |
| Enterprise Standard Answers | `ee/onyx/db/standard_answer.py` | Extract presentation-independent matching if needed; add an EE Teams adapter |
| Administration UI | Opal, existing bot pages, SWR patterns, Teams logo | Add `web/src/app/admin/teams-bot/`, navigation entry, and keys in all nine locale catalogs |
| SDK dependencies | Existing Python/FastAPI runtime | Update `pyproject.toml`, `uv.lock`, and generated requirements for the selected released SDK packages |
| Deployment | Existing images, ingress, Redis, Postgres, Celery | Update Compose template and generated variants, Helm routing/consumer settings, and environment docs |
| Teams packaging | Microsoft manifest schema | Add a versioned manifest template and required icons under `deployment/teams/` |
| Tests | Existing bot test layouts and manager helpers | Add Teams suites and targeted Slack/Discord regression coverage described below |

Use relational configuration for bot registrations and destination overrides.
Bind credentials to the verified Entra tenant and Onyx tenant; reject conflicting registrations atomically.
Track verified installations, identity links, conversation references, event status, and delivery IDs.
All database operations belong under `onyx/db`; raw secrets must not appear in response models.

Avoid a generic cache framework or a rewrite of all bots before Teams works.
The Discord API client authenticates a service account; reusing it unchanged cannot provide per-user Teams access.
Prefer the in-process generation service over introducing an HTTP impersonation feature.
If separate-process deployment later needs an API credential, use stable encrypted credentials with explicit rotation.
Do not copy cache-miss key regeneration into a horizontally scaled Teams service. [D7]

The existing Teams connector remains independent.
Reuse its indexed data and permission-sync results through the search pipeline, not its broad Graph app credential for bot actions.
Keep Slack-specific federated search context out of the Teams transport. [T1], [S8]

## Phased implementation and acceptance criteria

Estimates are engineering days for one experienced Onyx/Python/React developer.
They assume an available test tenant, administrator help, review access, and working Onyx services.
They exclude Microsoft approval delays, marketplace publication, and maintainer review time.
Split phases into small PRs; the repository asks for no more than 500 lines of real change per PR.
Enterprise changes also require the IP Assignment Agreement described in [CONTRIBUTING.md](../CONTRIBUTING.md).

| Phase | Scope and dependencies | Estimate | Acceptance criteria |
| --- | --- | --- | --- |
| P0: design and platform spike | Confirm SDK releases, FastAPI auth, worker continuation, tenant identity, target scopes; maintainer design review | 3–5 days | Valid signed activity and reply in a real test tenant; invalid JWT rejected; documented package/manifest/client matrix |
| P1: configuration and shared boundary | P0; encrypted config, migrations, admin API/UI, identity linking, isolated answer-service extraction | 6–9 days | Only `MANAGE_BOTS` can change config; no secret echo; tenant isolation and link ownership tests pass; Slack unchanged |
| P2: core chat release | P1; personal chat, standard-channel mentions, observed history, retrieval, citations, durable delivery, deployment | 8–12 days | Private/public document matrix passes; context survives restart; duplicate input does not repeat generation; correct thread and safe failures |
| P3: conversation/configuration parity | P2; group chat, RSC receive-all, authorized history reads, implicit replies, filters and user/group allowlists | 5–8 days | No-consent and revoked-consent cases work; unseen-history limits are explicit; channel override persists across follow-ups |
| P4: private answers and interactions | P2; targeted delivery, feedback, safe share, authenticated web continuation; SDK/client capability gate | 5–8 days | No private-to-public fallback; unauthorized/expired card actions rejected; supported clients verified; original private prompts remain private |
| P5: Slack-specific completion | P3/P4; EE Standard Answers, Generate Full Answer, reminders, escalation and resolution; bot-author policy | 4–7 days | CE/EE separation holds; reminders cancel after feedback; escalation stays in approved audience; capability gaps documented |
| P6: release validation | P1–P5; tenant isolation, upgrade/rotation/recovery tests, docs and administrator walkthrough | 4–6 days | Real Teams smoke suite passes; scoped Slack/Discord regressions pass; deployment/upgrade paths validated; maintainers review remaining gaps |

Core P0–P2: **17–26 engineering days**. Full planned scope: **35–55 days**, roughly **7–11 working weeks**.
The estimate is not a claim that all Microsoft platform gaps can be removed.
Private/shared-channel conversation support, cross-tenant central distribution, bot-to-bot delivery, and federated Teams search remain explicit gates or separate work.
A release must state which matrix rows are supported rather than advertise unconditional parity.

## Tests

Prefer integration tests for permissions, configuration, and persistence.
Use external-dependency tests for Microsoft SDK boundaries with controlled Microsoft responses and real Onyx dependencies.
Use unit tests only for pure normalization/rendering and isolated protocol validation.
Use Playwright Page Objects for the admin UI; a local browser test cannot prove real Teams delivery.

| Test area | Required cases and meaningful assertions |
| --- | --- |
| Authentication | Invalid signature, audience, issuer, expired token, wrong Entra tenant, unknown bot registration; reject before enqueue or generation |
| Tenant routing | Two Onyx tenants with colliding conversation IDs; no cross-tenant config, cache, source, session, or action lookup |
| Identity | Verified link, wrong-account link, spoofed email, renamed user, disabled/deleted user, seat limit, invite/domain denial, guest actor |
| Audience/ACLs | Public document plus Alice-only and Bob-only documents; private answers differ; shared answers never contain private text, titles, links, or tool output |
| Revocation | Revoke group/persona access after enqueue and before send; remove a recipient or installation; do not publish stale private answers |
| Trigger/context | Mentions, automatic roots, reply exceptions, personal/group chat without team ID, two parallel threads, quoted history, RSC absent/revoked |
| Visibility | Targeted and public traffic in one conversation; isolate histories; suppress public fallback and private Prompt Preview during sharing |
| Rendering | Citation-number mapping, duplicate/missing sources, unsafe URLs/HTML/mentions, code/table fallback, Unicode payload limits, attachment-only input |
| Delivery | Duplicate/out-of-order activities, concurrent workers, restart, queue expiration, timeouts, 429/413/403 responses, ambiguous send outcome; no extra generation on send retry |
| Actions | Replayed/expired/tampered feedback, cross-user answer ID, invoke response body/status, escalation/resolution, reminder cancellation, handoff ownership |
| Administration | `MANAGE_BOTS` access, secret masking, atomic registration conflicts, invalid agents, config disable/delete, rotation, channel reconciliation, migration upgrade |
| Real Teams | Desktop/web/mobile personal and standard channel flows; group/RSC/targeted tests for advertised features; record client versions and unsupported scopes |

Proposed suites: `backend/tests/integration/tests/teams_bot/`, `backend/tests/external_dependency_unit/teams_bot/`, and `web/tests/e2e/admin/teams-bot/`.
Add pure renderer/protocol tests under `backend/tests/unit/onyx/onyxbot/teams/` only where integration tests cannot isolate the edge case.
Live Microsoft credentials belong in the test-secret resolver, never in fixtures or committed manifests.
Backend calls made during local manual testing must go through the frontend `/api` route, as required by `AGENTS.md`.

Regression checks when extracting shared code:

- Slack: `test_slack_gating.py`, `test_slack_blocks.py`, `test_slack_formatting.py`, `test_slack_channel_config.py`, and `test_slack_socket_client_reaping.py`.
- Slack dependencies: `backend/tests/external_dependency_unit/slack_bot/`; verify public/private federated scope, token masking, persona denial, forced-search availability, and channel override retention.
- Slack users: `backend/tests/integration/tests/users/test_slack_user_deactivation.py` and `test_slack_service_account.py` at their existing test locations.
- Discord: `backend/tests/external_dependency_unit/discord_bot/`, `backend/tests/integration/tests/discord_bot/`, and `backend/tests/integration/multitenant_tests/discord_bot/`.
- Discord UI: `web/tests/e2e/admin/discord-bot/bot-config.spec.ts`; retain DM rejection, registration restrictions, default-disabled channels, thread behavior, and service-account semantics.
- Shared management: `backend/tests/integration/tests/permissions_membership/test_manage_bots.py`.

Run Python tests through `uv run` following `backend/AGENTS.md` and resolve declared secrets before live suites.
Run changed-file hooks, TypeScript/type-coverage checks, and applicable migration/deployment generators for implementation PRs.
This documentation-only proposal does not claim those runtime tests have been executed.

## Contribution proposal

TeamsBot would let organizations use their existing Onyx agents and indexed knowledge from Microsoft Teams.
It addresses requests from users moving from Slack and builds on the earlier TeamsBot proposals.
The design reuses Onyx's answer pipeline, document permissions, persona configuration, feedback storage, and administration patterns.
Microsoft's maintained Python SDK handles authenticated Teams transport.

Please review the parity matrix, shared-answer access policy, SDK choice, and initial supported scopes before implementation.
The work will arrive as small PRs with explicit acceptance criteria and regression coverage.
Teams-specific code stays in its adapter; Slack and Discord behavior remain covered by existing suites.
An administrator can enable one destination first and validate public/private retrieval before broader rollout.
The proposal seeks design agreement; it does not presume acceptance or promise unsupported Teams behavior.

## Source index

Local links refer to the audited baseline above. Microsoft links were checked on the research date.

[S1]: ../backend/onyx/onyxbot/slack/listener.py
[S2]: ../backend/onyx/onyxbot/slack/handlers/handle_regular_answer.py
[S3]: ../backend/onyx/onyxbot/slack/handlers/handle_message.py
[S4]: ../backend/onyx/onyxbot/slack/blocks.py
[S5]: ../backend/onyx/onyxbot/slack/handlers/handle_buttons.py
[S6]: ../backend/onyx/server/manage/slack_bot.py
[S7]: ../backend/onyx/db/models.py
[S8]: ../backend/onyx/context/search/federated/slack_search.py
[D1]: ../backend/onyx/onyxbot/discord/client.py
[D2]: ../backend/onyx/onyxbot/discord/handle_message.py
[D3]: ../backend/onyx/onyxbot/discord/api_client.py
[D4]: ../backend/onyx/onyxbot/discord/cache.py
[D5]: ../backend/onyx/server/manage/discord_bot/api.py
[D6]: ../backend/onyx/onyxbot/discord/handle_commands.py
[D7]: ../backend/onyx/db/discord_bot.py
[A1]: ../backend/onyx/access/access.py
[A2]: ../backend/onyx/db/api_key.py
[A3]: ../backend/onyx/server/query_and_chat/chat_backend.py
[E1]: ../backend/ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py
[T1]: ../backend/onyx/connectors/teams/connector.py
[O1]: https://docs.onyx.app/admins/getting_started/slack_bot_setup
[O2]: https://docs.onyx.app/admins/miscellaneous/discord_bot
[O3]: https://docs.onyx.app/admins/connectors/official/teams
[M1]: https://github.com/microsoft/Agents-for-python
[M2]: https://github.com/microsoft/botframework-sdk
[M3]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/channel-messages-for-bots-and-agents
[M4]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/channel-and-group-conversations
[M5]: https://learn.microsoft.com/en-us/microsoftteams/platform/build-apps-for-shared-private-channels
[M6]: https://learn.microsoft.com/en-us/microsoftteams/platform/agents-in-teams/targeted-messages
[M7]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/format-your-bot-messages
[M8]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/bots-filesv4
[M9]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/send-proactive-messages
[M10]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/build-conversational-capability
[M11]: https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0
[M12]: https://learn.microsoft.com/en-us/graph/api/chat-list-messages?view=graph-rest-1.0
[M13]: https://learn.microsoft.com/en-us/python/api/msteams-sdk-python/?view=msteams-sdk-python-latest
[M14]: https://learn.microsoft.com/en-gb/azure/bot-service/provision-and-publish-a-bot?tabs=singletenant%2Cpython&view=azure-bot-service-4.0
[M15]: https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/provision-azure-bot-service-manually
[M16]: https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/configure-authentication-msal
[M17]: https://learn.microsoft.com/en-us/microsoftteams/platform/resources/schema/manifest-schema
[M18]: https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/deploy-azure-bot-service-manually
[M19]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/authentication/bot-sso-overview
[M20]: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/authentication/bot-sso-register-aad
[M21]: https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/secure-your-agent
[M22]: https://github.com/microsoft/teams.py
