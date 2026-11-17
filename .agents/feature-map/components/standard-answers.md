# Standard Answers

> Admin-written canned answers that the Slack bot posts in place of an LLM answer
> when a message matches a keyword set or a regex. The match runs before
> retrieval, so the answer text never passes a document ACL.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** EE. CE runs a fallback that never matches.

---

## User experience

- **An admin** writes a standard answer: a keyword set or a regex, the answer
  text, and at least one category. Each Slack channel config then picks the
  categories it uses. The admin page is at `/admin/standard-answer`. It has no
  sidebar entry, so an admin reaches it by URL. The answer and category routes
  need full admin access, not the manage-bots permission
  (`ee/onyx/server/manage/standard_answer.py`).
- **A Slack user** in a channel with matching categories asks a question that
  contains the keywords. The bot replies at once with the canned answer,
  prefixed with the matched words, and a "Generate Full Answer" button. The
  button runs the normal LLM answer for the same question.
- **The same answer does not repeat in one Slack thread.** A later message in
  that thread gets another matching answer, or the LLM answer.
- **On a CE build, or after a Community downgrade,** nothing matches and no
  warning is shown. The downgrade sets every answer inactive.

---

## Scope

This component owns the match rules, the canned Slack reply and its saved chat
messages, the answer and category records with their admin API and admin pages,
the category selector that the Slack channel forms embed, and the one-off lookup
route `GET /query/standard-answer`.

Its neighbours own:
- [[slack-bot]]: the caller, the channel config that holds the categories, the
  channel forms, and the "Generate Full Answer" button handler.
- [[editions-and-gating]]: the CE fallback mechanism.
- [[billing]]: the Community downgrade that deactivates every answer.

The Discord bot has no standard answers.

---

## Architecture

```
slack handle_message
  -> handle_standard_answers                 CE; fetch_versioned_implementation
     -> _handle_standard_answers             EE
          channel categories -> candidate answers
          minus answers already used in this thread    ChatMessage.standard_answers
          find_matching_standard_answers               active answers only
          on match: ChatSession (user_id None) + user and assistant ChatMessage,
                    attach StandardAnswer rows, post blocks
  True  -> handle_message returns; no LLM turn
  False -> handle_regular_answer
```

**Matching.** `ee/onyx/db/standard_answer.py:find_matching_standard_answers`
has three modes. Regex mode runs `re.search` with `re.IGNORECASE`. Keyword mode
strips punctuation, lowercases, and splits on whitespace. It then needs all
keyword words in the message, or any one when `match_any_keywords` is set. The
request model rejects regex mode together with `match_any_keywords`, and
compiles the regex on save (`server/manage/models.py:StandardAnswerCreationRequest`).

**Scope of an answer.** Only the categories on the channel's
`SlackChannelConfig` decide which answers can fire there. A default "General"
category exists only on a deployment that sets `ENV_SEED_CONFIGURATION`,
because `ee/onyx/server/seeding.py:seed_db` returns before it calls
`create_initial_default_standard_answer_category` otherwise.

---

## Contracts and traps

1. `answer-text-no-acl` **The answer text has no document ACL.** The match
   never calls search, so whatever an admin types reaches every reader of the
   channel. Treat the category-to-channel assignment like a document
   permission. Do not put text in an answer that some channel readers must not
   see.
2. `lookup-route-bypasses-channel` **The lookup route bypasses the channel
   boundary.** `ee/onyx/server/query_and_chat/query_backend.py:get_standard_answer`
   needs only basic access. It takes category names from the caller and returns
   matching answer text. Any signed-in user who knows a category name and a
   keyword can read an answer, without access to the channel. A change to
   [[#answer-text-no-acl]] must cover this route too.
3. `no-regular-answer-checks` **The Slack path runs none of the regular-answer
   checks.**
   `ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py:_handle_standard_answers`
   runs no persona access check and no
   token budget check, and it creates the chat session with no user. That is
   correct for a reply with no LLM call. Do not add LLM work to this path
   without the checks in [[slack-bot#chat-route-depends-skipped]].
4. `visibility-from-receiver-list` **Visibility comes from the caller's
   receiver list.** The reply goes to `receiver_ids`, which `handle_message`
   sets from the channel allowlist. The channel's `is_ephemeral` setting does
   not apply, so in an ephemeral channel with no allowlist, or for a slash
   command, the canned answer posts publicly.
5. `dedup-reads-thread-history` **De-duplication reads the chat history of the
   Slack thread.** The used set comes from `ChatMessage.standard_answers` of
   every session with the same `slack_thread_id`. A change to how the handler
   saves messages, or to `db/chat.py:get_chat_sessions_by_slack_thread_id`, can
   break it without a failing test. The set is per thread, so all users in a
   thread share it.
6. `failed-post-marks-used` **A failed post still marks the answer used.** The
   handler commits the chat messages before it posts. If the post fails, it
   returns `False`, and the LLM answers instead. The answer then counts as used
   in that thread.
7. `deactivation-soft-delete` **Deactivation is a soft delete.**
   `ee/onyx/db/standard_answer.py:remove_standard_answer` sets `active=False`. Old messages keep their link to
   the answer. The partial unique index `unique_keyword_active` lets a new
   active answer reuse the keyword.
8. `category-in-use-undeletable` **A category in use cannot be deleted.**
   `ee/onyx/db/standard_answer.py:remove_standard_answer_category` refuses while an active answer or a Slack
   channel config references it. A concurrent write that attaches one makes
   the commit raise an `IntegrityError`, which it reports as the same refusal.

---

## Known issues

- **Regex mode is unanchored and unbounded.** `re.search` matches anywhere in
  the message, so a short pattern can fire often. An admin-written pattern with
  heavy backtracking runs on each message in the channel.
- **No test covers the match or the Slack short-circuit.** The Slack gating
  tests patch `handle_standard_answers` to return `False`.

---

## Dependencies

- [[slack-bot]]: the only caller, and the owner of the channel config.
- [[editions-and-gating]]: `fetch_versioned_implementation` selects the EE handler or the CE fallback.
- [[chat-persistence]]: matched answers are saved as `ChatMessage` rows linked through `ChatMessage__StandardAnswer`.
- [[billing]]: the Community downgrade deactivates every answer (`ee/onyx/db/community_downgrade.py`).

---

## Recipes

- `setup-canned-answer` **Set up a canned answer to reproduce a report.** On an EE build, create a
  category, then an answer in keyword mode, at `/admin/standard-answer`. Assign
  the category on the Slack channel config form ([[slack-bot]]). List the
  current active answers and categories with `GET
  /api/manage/admin/standard-answer` and `GET
  /api/manage/admin/standard-answer/category`. Use a new Slack thread for each
  attempt, because an answer fires once per thread
  ([[#dedup-reads-thread-history]]).
- `investigate-not-fired` **Investigate "the canned answer did not fire".** Check in order: the build
  runs EE code, the answer is active, the channel config holds one of its
  categories, the thread has not used it, and the sender passes the channel
  allowlist and filters in `handle_message`, which run before the match. In
  keyword mode every keyword word must be in the message unless "match any" is
  set.

---

## Verification

- External dependency: `backend/tests/external_dependency_unit/ee/db/` for
  category delete, and `backend/tests/external_dependency_unit/ee/onyx/db/`
  for the downgrade deactivation.
- By hand, on EE with a Slack app: assign a category to a channel, send a
  matching message, and confirm the canned answer with no LLM delay. Send it
  again in the same thread and confirm the LLM answers. Send it in a channel
  without the category and confirm no match.
