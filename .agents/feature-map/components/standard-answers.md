# Standard Answers

> A keyword or regex match against an incoming Slack message that, when it hits,
> replaces the LLM turn entirely with a pre-written answer. Enterprise Edition
> only. The match runs before retrieval, so the answer text is never subject to
> document-level ACL.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** integrations
**Edition:** EE
**Owns:**
`backend/ee/onyx/db/standard_answer.py`,
`backend/ee/onyx/server/manage/standard_answer.py`,
`backend/ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py`,
`backend/onyx/onyxbot/slack/handlers/handle_standard_answers.py` (CE fallback),
`web/src/app/ee/admin/standard-answer/`

---

## 1. What the user experiences

A workspace admin creates a standard answer at `/admin/standard-answer/new`: a
keyword or regex pattern, the answer text, and one or more categories
(`web/src/app/ee/admin/standard-answer/StandardAnswerCreationForm.tsx`). A Slack
channel config is assigned one or more of those categories. When a message in
that channel matches an assigned answer's pattern, the Slack bot posts the
canned answer directly, with a "Generate Full Answer" button, instead of running
retrieval and the LLM. The list and edit views live at `/admin/standard-answer`
and `/admin/standard-answer/[id]`.

---

## 2. Surfaces

| Surface | Where |
|---|---|
| `/admin/standard-answer`, `/new`, `/[id]` | `web/src/app/ee/admin/standard-answer/` |
| `POST/GET /manage/admin/standard-answer` | `ee/onyx/server/manage/standard_answer.py` |
| `PATCH/DELETE /manage/admin/standard-answer/{id}` | `ee/onyx/server/manage/standard_answer.py` |
| `POST/GET/PATCH/DELETE /manage/admin/standard-answer/category[/{id}]` | `ee/onyx/server/manage/standard_answer.py` |
| Slack channel config field `standard_answer_categories` | `backend/onyx/db/models.py:SlackChannelConfig` |

All admin endpoints require `Permission.FULL_ADMIN_PANEL_ACCESS`
(`ee/onyx/server/manage/standard_answer.py`), not a Slack-specific permission.

---

## 3. Data model

`StandardAnswer` (`backend/onyx/db/models.py:StandardAnswer`): `keyword` (a literal phrase
or a regex pattern, depending on `match_regex`), `answer` text, `active`
(soft-delete flag), `match_regex`, `match_any_keywords`. A partial unique index
enforces one active answer per `keyword` (`unique_keyword_active`, `postgresql_where=(active == True)`), so a deactivated keyword
can be reused by a new answer.

`StandardAnswerCategory` (`models.py:StandardAnswerCategory`): just an `id` and unique `name`.

`StandardAnswer__StandardAnswerCategory` (`models.py:StandardAnswer__StandardAnswerCategory`): many-to-many join,
which answers belong to which categories.

`SlackChannelConfig__StandardAnswerCategory` (`models.py:SlackChannelConfig__StandardAnswerCategory`) and
`SlackChannelConfig.standard_answer_categories`: which
categories are active for a given Slack channel. This is the scoping mechanism:
an answer only fires in a channel if one of its categories is assigned to that
channel's config.

`ChatMessage__StandardAnswer` (`models.py:ChatMessage__StandardAnswer`) and
`ChatMessage.standard_answers`: records which standard
answers were attached to a given assistant `ChatMessage`, added by
`backend/alembic/versions/c5eae4a75a1b_add_chat_message__standard_answer_table.py`.
`match_regex` was added later by
`backend/alembic/versions/efb35676026c_standard_answer_match_regex_flag.py`
(`server_default=false`); the base tables came from
`backend/alembic/versions/c18cdf4b497e_add_standard_answer_tables.py`.

---

## 4. How it works

```
handle_message.py: handle_standard_answers(...)                 onyx/onyxbot/slack/handlers/
  └─ fetch_versioned_implementation(..., "_handle_standard_answers")   [[editions-and-gating]]
        ├─ CE fallback: always returns False                    onyx/onyxbot/.../handle_standard_answers.py
        └─ EE: _handle_standard_answers(...)                     ee/onyx/onyxbot/.../handle_standard_answers.py
              ├─ diff configured categories' answers against ones already
              │  used in this Slack thread
              ├─ find_matching_standard_answers(query, id_in, db_session)   ee/onyx/db/standard_answer.py
              ├─ if matched: create a ChatMessage pair, attach
              │  chat_message.standard_answers, post the Slack blocks
              └─ returns True (matched) or False (no match)
if used_standard_answer: return False   # handle_message.py, LLM path never runs
else: handle_regular_answer(...)        # normal retrieval + LLM turn
```

1. `handle_message.py:handle_standard_answers` (CE) always dispatches through
   `fetch_versioned_implementation("onyx.onyxbot.slack.handlers.handle_standard_answers", "_handle_standard_answers")`.
   In a Community build (or before EE is loaded) the CE fallback in the same
   module always returns `False` and does nothing else
   (`onyx/onyxbot/slack/handlers/handle_standard_answers.py:_handle_standard_answers`).
   In an EE-enabled process, this resolves to the EE implementation. See
   [[editions-and-gating]] for how that dispatch is decided at import time.
2. The EE `_handle_standard_answers` (`ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py`)
   reads `slack_channel_config.standard_answer_categories`, collects every
   `StandardAnswer` in those categories, then subtracts any already used in the
   current Slack thread (via `ChatMessage.standard_answers` for chat sessions on
   that `slack_thread_id`) so the same canned answer is not repeated.
3. `find_matching_standard_answers` (`ee/onyx/db/standard_answer.py`) matches
   the latest thread message against the remaining candidates: if
   `match_regex` is set, `re.search(keyword, query, re.IGNORECASE)`; otherwise a
   punctuation-stripped, whitespace-tokenized keyword/query comparison, either
   "any keyword present" (`match_any_keywords=True`) or "all keyword words
   present".
4. On a match, the handler creates a chat session and a user/assistant
   `ChatMessage` pair directly in the database
   (`create_chat_session`, `create_new_chat_message`), attaches the matched
   `StandardAnswer` rows to `chat_message.standard_answers`, and posts the
   answer as Slack blocks (`build_standard_answer_blocks`). **No LLM call, no
   retrieval, no `run_llm_loop` invocation happens on this path.**
5. Back in `handle_message.py`, `used_standard_answer = handle_standard_answers(...)`;
   if `True`, the function returns immediately and `handle_regular_answer` (the
   retrieval-and-LLM path, see [[core-chat-loop]]) is never called. Only a
   `False` (no match, or CE build) falls through to the normal turn.

---

## 5. Contracts and invariants

1. **A match must be deterministic given the same configured categories and
   thread history.** `find_matching_standard_answers` has no randomness and no
   LLM in the loop; the same query against the same `usable_standard_answers`
   set always matches the same answers.
2. **A category must scope which channels can trigger an answer.** An answer
   fires only if it belongs to a category assigned to that channel's
   `SlackChannelConfig.standard_answer_categories`
   (`ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py:_handle_standard_answers`).
   An answer with no category assigned to any channel can never fire, by
   construction; a channel-config change that broadens categories broadens
   which answers leak into that channel, so category assignment is the only
   access boundary this feature has.
3. **The answer text bypasses retrieval and therefore bypasses document ACL
   entirely.** `oneoff_standard_answers` and `_handle_standard_answers` never
   call the search pipeline or check document permissions; the answer is
   whatever an admin typed. This is a deliberate design point, not a bug: admins
   write these answers, and they are scoped by category-to-channel assignment
   (§5.2), not by document-level ACL (see [[access-control]]). **Whether this is
   a concern**: it means anyone who can post in a channel whose config includes
   a category sees every answer in that category, regardless of their own
   document permissions elsewhere; if an answer's text embeds sensitive
   material, category assignment is the only control, so admins should treat
   category-to-channel assignment with the same care as a document ACL.
4. **A used answer is not repeated in the same Slack thread.** The "already
   used" set is computed from `ChatMessage.standard_answers` for chat sessions
   tied to the thread's `slack_thread_id`
   (`ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py`), so `remove_standard_answer`
   deactivating an answer does not retroactively un-mark it as used; deactivation
   only stops future matches (`ee/onyx/db/standard_answer.py:remove_standard_answer`
   sets `active=False`, it does not delete the row).
5. **Only active answers can match or be listed.** `find_matching_standard_answers`
   and `fetch_standard_answers` both filter `StandardAnswer.active.is_(True)`
   (`ee/onyx/db/standard_answer.py`); the partial unique index on
   `(keyword, active)` (`unique_keyword_active`) lets a new active answer reuse a
   deactivated keyword.
6. **A category in use cannot be deleted.** `remove_standard_answer_category`
   refuses deletion if any active answer or Slack channel config still
   references it, and re-checks after commit under an `IntegrityError` race
   (`ee/onyx/db/standard_answer.py:remove_standard_answer_category`).

---

## 6. Relationships

**Depends on**
- [[editions-and-gating]]: the CE/EE dispatch in
  `onyx/onyxbot/slack/handlers/handle_standard_answers.py` is what turns this
  feature on or off; in Community Edition it is always a no-op.
- [[slack-bot]]: `handle_message.py` is the only caller; the match happens
  before `handle_regular_answer`, the Slack bot's normal turn path.
- [[chat-persistence]]: matched answers are persisted as ordinary `ChatMessage`
  rows via `create_chat_session`/`create_new_chat_message`, joined to their
  `StandardAnswer` rows through `ChatMessage__StandardAnswer`.
- [[access-control]]: deliberately not used for the answer text itself; see §5.3.

**Depended on by**
- [[discord-bot]]: does not call into this component; Discord has no
  standard-answer integration (see that document's §6 comparison).

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| changes `find_matching_standard_answers`' matching logic | whether `match_regex`/`match_any_keywords` semantics still hold; regex changes can turn a narrow keyword into one that matches unintended messages |
| adds a new category-assignment surface | §5.2's scoping invariant: every new place a category can be attached becomes a new place an answer can leak into a channel |
| changes what `_handle_standard_answers` persists to `ChatMessage` | the "already used in thread" dedup logic (§5.4), which reads `ChatMessage.standard_answers` back |
| changes the CE/EE dispatch point | [[editions-and-gating]]; confirm the CE fallback in `onyx/onyxbot/slack/handlers/handle_standard_answers.py` still always returns `False` |
| removes or restricts the LLM short-circuit | confirm `handle_message.py`'s `if used_standard_answer: return False` still runs before `handle_regular_answer` |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/external_dependency_unit/ee/db/test_standard_answer_category_delete.py
```

This is the only test file found under this name in the repository. No unit test
targets `find_matching_standard_answers`' match logic directly, and no
integration or playwright test exercises the Slack short-circuit path or the
`/admin/standard-answer` UI.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Create a category and a standard answer at `/admin/standard-answer/new`,
   sign in as `admin_user@example.com` / `TestPassword123!`.
3. Assign the category to a Slack channel config (Slack bot admin panel).
4. Send a matching message in that Slack channel and confirm the canned answer
   posts with no delay characteristic of an LLM call.
5. Send the same message again in the same thread and confirm the answer is not
   repeated (§5.4).

### What "working" looks like

- A matching message in a scoped channel gets the canned answer immediately,
  with a "Generate Full Answer" button, and no `run_llm_loop` invocation in the
  logs for that turn.
- The same answer does not repeat within one Slack thread.
- A message in a channel whose config does not include the answer's category
  never triggers it, even if the keyword matches.

---

## 9. Footguns

- **This is EE-only and silently inert on Community Edition.** The CE fallback
  in `onyx/onyxbot/slack/handlers/handle_standard_answers.py` always returns
  `False`; there is no error, warning, or admin-visible indication that standard
  answers are configured but never firing on a CE build.
- **The answer text is not access-controlled.** See §5.3. Do not treat a
  standard answer as safe to contain anything a document ACL would otherwise
  protect.
- **Deactivating an answer does not retroactively hide it from `ChatMessage`
  history.** Old messages keep their `ChatMessage__StandardAnswer` association
  even after the answer's `active` flag flips to `False`.
- **Regex mode uses `re.search`, not `re.match` or `re.fullmatch`.** An
  unanchored pattern can match a substring anywhere in the message, which is a
  common source of over-broad matches (`ee/onyx/db/standard_answer.py:find_matching_standard_answers`).
- **A used-status check keys off `slack_thread_id`, not the answer or the
  user.** Two different users in the same Slack thread share the "already
  answered" state.

---

Cross-links: [[slack-bot]], [[core-chat-loop]], [[access-control]],
[[editions-and-gating]], [[rate-and-usage-limits]], [[agents-personas]],
[[chat-persistence]]
