# Teams

> The Microsoft Teams connector indexes channel threads, channel files, meeting
> transcripts and the days of meeting chats from one app credential. It reads
> channel messages through the Graph export API when the tenant allows it, and
> walks channel by channel when it does not.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE syncs readers through the slim listing.

---

## User experience

An admin connects a Microsoft Entra app and picks teams by display name, or
none for every team. Channel threads are always indexed. Channel files, pasted
images, meeting transcripts and meeting chats are each off by default, because
each needs more Graph grants or costs more requests. Transcripts and chats are
read for chosen organizers, or for every licensed user when none are named.
Search returns one document per channel thread, per file, per transcript and per
day of a meeting chat.

When a grant is missing, the generic "Test connection" row fails at creation
and names the Graph permission that each turned-on option needs
(`TeamsConnector.validate_connector_settings`). Channel files with a client
secret fail there too, because they need a certificate. A named organizer that
matches no user fails the check. With no organizers named, the check probes one
licensed user, so an access policy that covers only some users passes and then
refuses the others at index time. Each refused organizer shows as one failure
in the pair's failure list. A tenant that turns transcript export off fails the
attempt.

---

## Scope

This document holds the Teams rules: the step order of the crawl, the export
path and the channel walk, files, organizers, and the export refusals. Its
neighbours own:
- [[microsoft-graph]]: Graph auth, national-cloud hosts and SharePoint REST
  permission reads.
- [[connectors]]: the interfaces and the prune contract.
- [[connector-capability-checks]]: the generic settings check. Teams has no
  `SourceOperations` gateway and no named checks, so its form runs that row.
- [[permission-sync]]: the EE doc sync, which reads channel and file readers
  from the slim listing.

---

## Architecture

**Teams, then channels.** The first step lists every team
(`connectors/teams/listing.py:collect_all_teams`). The first team step probes the export API
once and stores the answer in `TeamsCheckpoint.export`, so every step of the
attempt takes the same path.

**Export path.** With the export API, a step streams `EXPORT_TEAM_WORKERS`
teams at a time (`connectors/teams/export.py:ExportSource`). One stream per team carries every
message changed in the window, replies included. A thread whose root was
created inside the window is complete in the stream. An older thread that
changed gets its replies from Graph. A team whose stream Graph refuses, or that
streams more than `EXPORT_MESSAGES_CAP` messages, goes to the channel walk.

**Channel walk.** Without the export API, a team's channels go into
`todo_channels`. `_channel_step` walks one delta page of up to `max_workers`
channels at once, then one replies call per root.

**Files.** After a channel's last page, its library is read on a worker thread
(`connectors/teams/files.py:FileSource`). File readers come from SharePoint REST, through a
context kept per site and per thread.

**Organizers.** After the channels, a step lists a page of licensed users, then
`connectors/teams/organizers.py` drains `ORGANIZER_BATCH` organizers with `ORGANIZER_WORKERS`
workers. On a poll, one chats export stream per organizer says which chat days
changed (`connectors/teams/meeting_chats.py:fetch_touched_days`), so a quiet chat costs no
request.

**Prune and permission sync.** `_slim_docs` lists the channels again through
the delta, ids only, then the organizers the same way.

---

## Contracts and traps

1. `channel-step-all-or-none` **A channel step writes back all cursors or none.**
   `connectors/teams/connector.py:TeamsConnector._channel_step` advances
   cursors on copies and writes them back only when every channel finished its
   page. A raise in one channel retries the whole step. Keep this when you add
   per-channel state, or a retry skips pages.
2. `export-refusal-routing` **A 402 from the export API means the tenant meters it.** Graph refuses the
   export API with 403 to an app without approval and with 402 to a metered
   tenant (`connectors/teams/refusals.py`). At the first probe, both send every team to
   the channel walk. A 404 or 423 at the probe refuses that team only, and the
   next team probes again. During a team's stream, a 402 sends every remaining
   team to the channel walk, and another permanent refusal sends only that
   team. Any other error is an outage and raises.
3. `export-to-request-time` **The export stream runs to the request time, not the window end.** A reply
   edited during the attempt is in this stream, and the next window lists it
   again. This is deliberate, to match a live replies call.
4. `teams-by-name` **Team names, not ids.** The `teams` setting matches display names, which
   Graph does not keep unique. A renamed team leaves the scope.
5. `slim-ignores-start` **The slim listings ignore `start`.** `slim_listing_honors_indexing_start`
   is `False`, because files, transcripts and chats list without a date
   filter. A prune of a pair with an indexing start lists everything.
6. `files-need-certificate` **Channel files need a certificate credential and a sites grant.** File
   readers come from SharePoint REST, which needs both
   (`connectors/teams/connector.py:TeamsConnector.__init__` comment).
7. `old-keys-still-read` **Old checkpoint fields and config keys are still
   read.** A saved checkpoint can hold `current_channel` and
   `next_messages_url` from the one-channel walk;
   `connectors/teams/connector.py:TeamsConnector.load_from_checkpoint` moves them into `active`. A stored
   config can hold `transcript_organizers`, which counts only while
   `meeting_organizers` is empty (`connectors/teams/config.py`). Saved
   checkpoints and configs outlive a deploy, so keep both reads until no
   stored row holds the old shape.

---

## Known issues

- **One transient failure discards the other channels' finished pages.** The
  retry repeats up to `max_workers - 1` pages of replies calls. The code
  accepts this cost over a partial write-back.
- **Targeted re-index reads only transcripts.** `TeamsConnector.reindex`
  rebuilds failed transcript documents. A failed thread, file or chat day
  needs a full re-index.
- **Teams has no gateway.** SDK and HTTP calls are spread across the package,
  so the import fence and check coverage tests do not apply to it.

---

## Dependencies

- [[connectors]]: interfaces and the prune contract.
- [[microsoft-graph]]: auth, national-cloud hosts and SharePoint REST reads.

---

## Recipes

- `investigate-channel-walk` **Investigate why a team uses the channel walk.** The first team step stores
  the export probe's answer in `TeamsCheckpoint.export` for the whole attempt.
  Look in the backend log for "The export API is not available" and its
  status: 403 means the
  app has no export approval, 402 means the tenant meters the API, and both send
  every team to the channel walk ([[#export-refusal-routing]]). A team that
  streams more than `EXPORT_MESSAGES_CAP` messages also falls back.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/teams/`.
- Daily tests against a live tenant: `backend/tests/daily/connectors/teams/`.
