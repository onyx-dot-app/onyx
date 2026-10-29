# Federated Search

> Search of a source at query time through its own API, with no indexing.
> `FederatedConnectorSource` lists the sources, and their results join the
> same ranked set, document cards and citations as indexed documents.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

- **An admin** adds a federated Slack connector from the connector catalog. The
  admin enters the Slack app's client ID and secret and the channel scope, and
  can link the connector to document sets.
- **A user** connects their own Slack account from their settings page, or from
  a prompt in the chat app that they can skip. After the OAuth flow, a search in
  chat can return Slack messages. Each message shows as a document card and a
  numbered citation that opens the message in Slack. The user cannot tell a
  live Slack result from an indexed one.
- **A Slack bot user** gets Slack results through the bot only when the
  agent's document sets include one linked to the federated Slack connector.
  The search then uses the tokens of the tenant's Slack bot, not the asker's own
  account.
- **An API caller** of `POST /search` gets Slack results from their own
  connected Slack account, ranked with the indexed results.
- **When it fails**, the user sees no error. With no token, an expired token, or
  a Slack API error, the search runs without Slack and the answer has no Slack
  sources. The user must reconnect Slack after the token expires.

---

## Scope

This component owns the federated connector framework and registry, the Slack
federated client and its retrieval, the federated connector and OAuth token
records, the `/federated` API, and the admin form and per-user connect flow.
It owns the token and gate rules of the Slack lane, though the lane is a method
on `SearchTool`.

Its neighbours own:
- [[internal-search]]: `SearchTool`, the lane fan-out, rank fusion, LLM
  selection and expansion.
- [[connectors]]: the indexed Slack connector, which is a separate feature.
- [[access-control]] and [[permission-sync]]: the index ACL. Federated results
  do not use it.
- [[slack-bot]]: `SlackContext` and the tenant Slack bot row.

---

## Architecture

```
SearchTool.run  (one DB session, before any parallel work)
  -> get_federated_retrieval_functions      skips Slack, so it returns [] for every source
  -> _prefetch_slack_data                    bot token (bot context, gated by
                                            document sets) or the user's OAuth token
  -> parallel lanes: index queries + one _run_slack_search lane
       _run_slack_search -> slack_retrieval  Slack search API -> thread context
         -> IndexingDocument -> Chunker
         -> InferenceChunk(is_federated=True, document_id="<channel>_<ts>")
  -> weighted_reciprocal_rank_fusion -> selection -> expansion -> citations
```

**Two mechanisms.** The generic registry path
(`federated_connectors/federated_retrieval.py:get_federated_retrieval_functions`)
builds one retrieval function per user OAuth token. It skips every
`FEDERATED_SLACK` token with the comment "Slack is handled separately inside
SearchTool". `configs/constants.py:FederatedConnectorSource` has only
`FEDERATED_SLACK`, so the registry returns an empty list at every call site.
The real Slack path is
`tools/tool_implementations/search/search_tool.py:SearchTool._run_slack_search`,
which runs once per tool call as its own lane. One lane per call avoids one
Slack API search for each expanded query.

**Token choice.** `SearchTool._prefetch_slack_data` runs only when
`enable_slack_search` is true or the call has a `slack_context`.
- Bot context: the persona's document sets must map to a `FEDERATED_SLACK`
  connector through `FederatedConnector__DocumentSet`. If they do, it picks an
  enabled Slack bot, and prefers one with a `user_token`. The access token is
  `user_token or bot_token`.
- If no token is found yet and the call has a user, it takes the user's
  `FederatedConnectorOAuthToken` for Slack. This branch has no document-set
  check.

Chat sets `enable_slack_search` through
`chat/process_message.py:_should_enable_slack_search`: true for the default
agent with no source filter, or when the source filter includes Slack. The
`/search` API (`server/features/search/api.py`) always sets it. After scope
detection, `SearchTool.run` drops the Slack token when the resolved scope
excludes `DocumentSource.SLACK`. The lane also needs `original_query`, and it is
skipped when the primary model's cost check fails, because `slack_retrieval`
uses that model for query processing.

**Shape of results.** `slack_retrieval` builds the same `IndexingDocument` and
`Chunker` output as indexing. It uses the embedding model's tokenizer to chunk,
but it computes no embeddings. The chunk score comes from the Slack match score
(`convert_slack_score`). The `InferenceChunk` objects then fuse with indexed
chunks like any other lane.

**Entity config.** Channel filters, DM inclusion and the default search window
come from `FederatedConnector.config`. Search does not read the `entities`
column on `FederatedConnector__DocumentSet`; the document-set API only stores
and returns it. On the `SearchTool` path the config shapes only the Slack query
string (`context/search/federated/slack_search_utils.py:build_channel_query_filter`)
and the extra DM queries in `slack_retrieval`. It does not filter results by
channel type ([[#slack-results-have-no-acl]]). The admin form shows the fields
of `federated_connectors/slack/federated_connector.py:SlackFederatedConnector.entities_schema`,
and search parses the stored config with
`federated_connectors/slack/models.py:SlackEntities`. A new config field needs
both.

---

## Contracts and traps

1. `slack-results-have-no-acl` **Onyx applies no ACL to Slack results. The
   token decides what comes back.**
   `tools/tool_implementations/search/search_tool.py:SearchTool._run_slack_search` builds
   `IndexFilters(access_control_list=None)` and passes no `effective_filters`.
   In a bot turn the token belongs to the Slack bot install, so results show
   what that token can see, not what the asker can see. The bot branch prefers
   the bot's `user_token`, which is a person's token and can read that person's
   private channels and DMs. Any change to token choice is a data-exposure
   review ([[slack-bot]], [[access-control]]). Check these places first in a
   leak report:
   - `context/search/federated/slack_search.py:_should_skip_channel` is the only channel-type filter that runs on this
     path. It drops private channels, IMs and MPIMs only when `bot_token` is
     set and `include_dm` is false, so it never runs for a web user's token.
     It keeps the private channel the question came from
     (`allowed_private_channel`). If it cannot read the channel type, it drops
     the message.
   - `context/search/federated/slack_search.py:slack_retrieval` sets `include_dm` and `allowed_private_channel` from
     `SlackContext` only when the connector config (`entities`) is empty. With
     a configured connector, both keep their defaults, so a bot asked in a DM
     or a private channel drops results from that DM or channel too.
   - `context/search/federated/slack_search.py:_fetch_thread_from_url` fetches a thread from a Slack URL in the
     question (`DirectThreadFetch`) with the access token. It never calls
     `_should_skip_channel`, so the bot branch can return a private thread.
   - The post-filter
     `context/search/federated/slack_search_utils.py:should_include_message` runs only when `entities` and
     `team_id` are both set. `_run_slack_search` passes `team_id=None`, so it
     never runs on this path (see Known issues).
2. `token-branches-asymmetric` **The two token branches are not symmetric.**
   Only the bot branch of `tools/tool_implementations/search/search_tool.py:SearchTool._prefetch_slack_data` checks the document-set link.
   A web user's Slack results are scoped by their own token, not by the agent's
   document sets. In the bot branch, a change that reads a token before the
   document-set check lets Slack search run outside that scope. Do not assume a
   change to one branch applies to the other.
3. `registry-skip-in-step` **The registry skip and the `SearchTool` lane must
   stay in step.** Only the `FEDERATED_SLACK` skip in
   `federated_connectors/federated_retrieval.py:get_federated_retrieval_functions` stops both mechanisms from fetching
   Slack. If you remove the skip, or add a second source whose token the
   registry does not skip, check for duplicate Slack results.
4. `missing-token-no-results` **A missing or failed token must give no results,
   not a failed turn.** `tools/tool_implementations/search/search_tool.py:SearchTool._prefetch_slack_data` catches errors
   in both token branches, and `tools/tool_implementations/search/search_tool.py:SearchTool._run_slack_search` returns `[]` on any error. No code checks
   `expires_at` before use, so an expired token fails at the Slack API call.
   The document-set lookup in the bot branch is outside the `try` blocks and
   can raise.
5. `slack-chunks-not-special` **Do not special-case Slack chunks after
   `_run_slack_search`.** Fusion, selection, expansion and citation numbering
   treat them like indexed chunks ([[citations]]). A change to chunk
   construction in `context/search/federated/slack_search.py` must keep the
   `InferenceChunk` shape.
6. `oauth-callback-no-token` **The OAuth callback never returns a token to the
   browser.** `server/federated/models.py:OAuthCallbackResult` has no token
   field, and `server/federated/api.py:handle_oauth_callback_generic` checks that the signed-in user
   matches the OAuth state. Do not add a token to the response.
7. `one-registry-fetch-per-call` **Two registry call sites do not mean two
   fetches.** `tools/tool_implementations/search/search_tool.py:SearchTool.run` calls the registry once and passes the result to
   every lane as `prefetched_federated_retrieval_infos`.
   `context/search/retrieval/search_runner.py:search_chunks` calls the registry
   itself only when nothing was prefetched. That happens on the EE Search page
   path (`ee/onyx/search/process_search_query.py`).

---

## Known issues

- **Refresh tokens are discarded.** The Slack callback
  (`federated_connectors/slack/federated_connector.py:SlackFederatedConnector.callback`)
  reads `refresh_token` into `OAuthResult`, but
  `db/federated.py:update_federated_connector_oauth_token` stores only `token`
  and `expires_at`. No job refreshes tokens. A Slack app that rotates tokens
  sends an expiry, and the user must reconnect after it. The comment on
  `OAuthCallbackResult` says the refresh token is stored encrypted; it is not.
- **Part of the connector config has no effect in chat.**
  `SearchTool._run_slack_search` passes `team_id=None` to `slack_retrieval`,
  so it loads no channel metadata. Without it, the `include_private_channels`,
  `include_dm` and `include_group_dm` post-filter does not run, glob channel
  patterns match no channel, and `exclude_channels` with
  `search_all_channels` adds no exclusion. A web user's token then returns
  every channel type that the token can read. The registry path
  (`SlackFederatedConnector.search`) looks up `team_id`, but nothing calls it.
- **The EE Search page never returns Slack results.** It calls
  `search_pipeline` directly, so it reaches only the registry path, which skips
  Slack.
- **The framework is built for many sources, but only Slack exists.** Read
  `federated_connectors/interfaces.py`, `federated_connectors/registry.py` and
  `federated_connectors/factory.py` with that in mind.
- **A user sees no sign that Slack was skipped.** The turn finishes with no
  Slack sources and no message.

---

## Dependencies

- [[internal-search]]: `SearchTool` runs the Slack lane and fuses its results.
- [[slack-bot]]: supplies `SlackContext` and the Slack bot tokens
  (`db/slack_bot.py:fetch_slack_bots`).
- [[auth-and-identity]]: OAuth tokens are keyed to `User.id`.
- [[connectors]]: `slack_retrieval` reuses the document models in
  `onyx.connectors.models`, not the [[slack]] connector.
- [[citations]]: Slack chunks get citation numbers like indexed chunks.
- [[editions-and-gating]]: the app credentials and OAuth tokens use encrypted
  column types, which encrypt only when EE code is loaded.

---

## Recipes

- `new-federated-source` **Add a second federated source.** Copy
  `federated_connectors/slack/federated_connector.py:SlackFederatedConnector`.
  Add a `FederatedConnectorSource` member and its `to_non_federated_source`
  mapping, implement every abstract method of
  `federated_connectors/interfaces.py:FederatedConnector`, and register the
  class in `federated_connectors/registry.py`. List the current sources with
  `git grep -n "class FederatedConnectorSource" -A4 backend/onyx/configs/constants.py`.
  Decide whether it uses the registry path or its own lane in `SearchTool`. On
  the registry path it is the first source to run there in production: test
  the document-set filter in `get_federated_retrieval_functions`, the
  resolved-scope filter in `SearchTool.run`, and [[#registry-skip-in-step]].
- `token-refresh` **Add token refresh.** Add a refresh-token column with an encrypted type,
  store it in `update_federated_connector_oauth_token`, and refresh before
  `_prefetch_slack_data` reads the token.
- `investigate-slack-leak` **Investigate a Slack result a user should not see.** First find the branch:
  a Slack bot turn has a `slack_context`, a web turn does not. For a bot turn,
  check which bot row supplied the token and whether it has a `user_token`.
  Then walk the list in [[#slack-results-have-no-acl]].
- `manual-slack-setup` **Set up Slack search by hand.** You need a real Slack app. Add the
  federated connector, connect Slack from the settings page, and ask a question
  that only Slack can answer. A citation must open the Slack message. Then
  disconnect Slack and ask again: the turn must finish with no Slack sources
  and no error.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/context/search/federated/`,
  `backend/tests/unit/onyx/federated_connectors/` and
  `backend/tests/unit/federated_connector/`.
- Bot path: `backend/tests/external_dependency_unit/slack_bot/`.
