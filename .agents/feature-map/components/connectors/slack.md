# Slack

> The Slack connector indexes channel threads as one document per thread. It
> reads Slack only through its gateway, the one module that imports `slack_sdk`
> in the connector and its EE permission sync.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE syncs channel membership as document readers
(`ee/onyx/external_permissions/slack/`).

---

## User experience

An admin connects a Slack bot token and picks channels to include or exclude,
by exact name or id, or by regex. The form can list the channels the token can
read, and the admin picks from that list. A picked channel is stored by id, so
it stays in scope after a rename. A typo in an exact include entry fails the
run with an error that names the unknown channel. Search returns one document
per thread. With EE permission sync, a thread is readable by the members of its
channel.

---

## Scope

This document holds the Slack connector rules: thread document ids, the
channel filter, the checkpoint and the gateway. Its neighbours own:
- [[connectors]]: the interfaces, gateway and prune contracts.
- [[connector-capability-checks]]: the check runner. Slack registers named
  checks, including the readable-channel listing that fills the channel picker.
- [[permission-sync]]: the EE doc sync, which reads channel members through the
  gateway.
- [[slack-bot]]: the bot imports helpers from the connector's utils module and
  one model from the gateway, so a change there reaches the bot.
- [[federated-search]]: federated Slack search does not import this package. It
  is a false lead for a bug in indexed Slack documents.

---

## Architecture

**Document id.** `connectors/slack/connector.py:build_slack_doc_id` gives
`<channel_id>__<thread_ts>`. `reindex` parses it back and reads each thread
again with `conversations.replies`, after it applies the channel scope with
`channel_in_scope`.

**Checkpoint.** `SlackCheckpoint` holds the channel ids, a per-channel
completion map, and `current_channel_access`. The last field carries an
in-flight channel's readers across a checkpoint boundary, because `external_access`
is set on each document as it is yielded.

**Channel filter.** `filter_channels` applies includes, then excludes. An exact
entry matches a channel id or name. A regex matches the name only.

**Errors for checks.** `connectors/slack/source_operations.py:slack_api_error_detail` chains a
`SlackApiError` to a `SourceApiError` that carries the request and Slack's
response body, so a failed check shows them as Error Details.

---

## Contracts and traps

1. `regex-timeout-narrows` **A regex timeout always narrows the scope.**
   `connectors/slack/connector.py:_channel_matches` counts a timed-out include regex as no match and a
   timed-out exclude regex as a match. A slow pattern never widens the scope.
2. `exact-includes-validated` **Exact include entries are validated, other
   entries are not.** An unknown exact include entry raises in
   `connectors/slack/connector.py:_validate_channels_exist`. A regex include that matches nothing and an
   unknown exclude entry are ignored.
   `connectors/slack/connector.py:channel_in_scope`, used by `reindex`,
   skips the include check.
3. `slim-ignores-start` **The slim listing ignores `start`.** A thread whose root is older than the
   indexing start is indexed through a newer broadcast reply, but the slim
   listing lists only the reply. `slim_listing_honors_indexing_start` is
   therefore `False`, and a prune lists every thread.
4. `variant-required` **Variant operations must name their variant.** Listing
   private channels needs `groups:read`, so `conversations.list` is a variant
   operation. A call without `variant=` raises `TypeError`
   (`connectors/source_operations.py:_enforce_variant_kwarg`).
5. `reindex-refuses-out-of-scope` **Re-index refuses out-of-scope threads**
   (`connectors/slack/connector.py:SlackConnector.reindex`). Archived channels, DMs and
   channels outside the crawl's filter fail, so a re-index cannot add a
   document that a crawl would not.

---

## Dependencies

- [[connectors]]: interfaces, gateway and prune contracts.
- [[connector-capability-checks]]: runs the Slack named checks.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/slack/`.
- Daily tests against a live workspace: `backend/tests/daily/connectors/slack/`.
