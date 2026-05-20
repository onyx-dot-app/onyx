# Phase 3 — Chat Approval UI (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2.

## Goal

Render the approval surface inline in the chat. An `approval_request`
`BuildMessage` (written by Phase 2 inside the same transaction as the
`approval_request` row) becomes an interactive card with Approve / Reject
buttons. An `approval_resolved` `BuildMessage` becomes a terminal card
with disabled buttons.

The card is durable on the conversation, so a user who closes and
reopens the tab during the request lifetime can still act. Once the
request times out (proxy's 180s wait), Phase 2 has already written the
resolved row with `decision: "expired"`; the user sees the terminal
card on reload.

## Module layout

All changes are frontend; Phase 2 owns the backend writes.

```
web/src/app/craft/components/
  BuildMessageList.tsx                       # new dispatch branch
  ApprovalCard.tsx                           # new
  ApprovalResolved.tsx                       # new (or co-located in ApprovalCard.tsx)
  PayloadView.tsx                            # new; per-kind payload renderer

web/src/app/craft/services/apiServices.ts    # postApprovalDecision
web/src/app/craft/hooks/useApprovalPolling.ts  # new; fallback poller
web/src/lib/notifications/interfaces.ts      # APPROVAL_REQUESTED enum value
```

## Tasks

### T3.1 — Add a `message_metadata.type` dispatch path in `BuildMessageList`

`renderAgentMessage` today branches on whether `message.message_metadata?.streamItems`
is populated; otherwise it falls back to rendering `message.content` via
`TextChunk`. There is no existing dispatch off `message_metadata.type`;
this phase introduces it.

Add a top-of-function check before the existing `savedStreamItems`
branch:

```tsx
const meta = message.message_metadata;
if (meta?.type === "approval_request") return <ApprovalCard message={message} />;
if (meta?.type === "approval_resolved") return <ApprovalResolved message={message} />;
```

The approval card reads only from `message_metadata`. The synthesized
`content` field (built by `fetchMessages` via `extractContentFromMetadata`)
is irrelevant for these messages.

### T3.2 — `ApprovalCard` component

Behavioral contract:

- Input: a `BuildMessage` whose `message_metadata` matches the
  `approval_request` shape from Phase 2 (`approval_id`, `kind`,
  `summary`, `payload`).
- Renders: kind label, `summary` text, `<PayloadView>` for the
  structured payload, Approve and Reject buttons.
- On button click: immediately disable both buttons (local state),
  then POST the decision via `postApprovalDecision`.
- On success: keep buttons disabled; the resolved `BuildMessage`
  arriving (via notification refetch or polling) replaces the card with
  `ApprovalResolved`.
- On CONFLICT (already decided or expired): call `refetchMessages()` so
  the resolved row renders.

### T3.3 — `ApprovalResolved` component

Renders the disposition (Approved / Rejected / Timed out) as a small
card styled to match existing message-card primitives. Buttons are
disabled or absent.

### T3.4 — `PayloadView` per-kind renderers

Per-kind rendering for the v0 action set:

- `slack.send_message` (Slack `chat.postMessage`): channel name and
  message body. Truncate the body at ~300 chars with a "show more"
  expander.
- `linear.create_issue` (Linear `IssueCreate`): team key, issue title,
  truncated description.
- `gcal.create_event` (GCal `events.insert`): event title, start time,
  attendee count.
- **Malformed-payload fallback for known kinds.** If a known-kind
  payload is missing fields the renderer expects (e.g.
  `slack.send_message` without `channel`), render the kind label and
  fall through to the JSON pretty-print path with a small "Payload
  did not match expected shape" notice. Do not throw or render a
  blank card.
- **Fallback for unrecognized kinds**: JSON pretty-print of `payload`.

### T3.5 — `postApprovalDecision` helper

Add to `apiServices.ts`, mirroring the existing fetch conventions in
that file (`/api/build/...` rewrite path, no explicit `credentials`,
JSON content type, throw on non-OK). Example signature:

```ts
async function postApprovalDecision(
  approvalId: string,
  decision: "approve" | "reject",
): Promise<void>
```

On 409 CONFLICT, throw an `ApprovalConflictError` the card can catch
distinctly from generic errors.

### T3.6 — Notification handling + polling fallback

Two paths feed the chat:

1. **Notification stream.** Add `APPROVAL_REQUESTED` to
   `web/src/lib/notifications/interfaces.ts`. When the chat is open on
   the targeted session and a notification of this type arrives, call
   `refetchMessages` for that session. This is the fast path.
2. **Polling fallback.** SSE / notification streams can drop without
   the user noticing. Add `useApprovalPolling(sessionId)` that polls
   `GET /api/build/sessions/{sessionId}/messages` every 10s while the
   session has at least one in-flight tool call (or any unresolved
   `approval_request` message). Stop polling when the session goes
   idle. The 10s cadence gives ~18 polls inside the proxy's 180s
   wait window — fast enough for the card to appear within one user
   beat if the notification dropped, slow enough that the polling
   cost is negligible.

The popover itself needs no logic change for v0; `APPROVAL_REQUESTED`
notifications render with default UI and deep-link to the session.

## Testing

- **Playwright (happy path).** Stand-in sandbox triggers a gated
  request, card appears inline within ~1s of the proxy hitting the
  service, click Approve, assert the resolved card replaces the
  original and the upstream action completes.
- **Component tests.**
  - `ApprovalCard` renders correctly for each of the three v0 kinds
    (`slack.send_message`, `linear.create_issue`, `gcal.create_event`)
    plus the unknown-kind fallback.
  - Click disables buttons immediately, before the await resolves.
  - On simulated CONFLICT response, `refetchMessages` is called.
  - `ApprovalResolved` renders the three terminal decisions
    (approve / reject / expired) with disabled buttons.

No backend tests in this phase; Phase 2 owns the writes.

## Dependencies

- Phase 2 merged: `approval_request` row, `approval_request` `BuildMessage`,
  and `approval_resolved` `BuildMessage` are all written by
  `service.create` / `service.respond` / `await_decision`-on-timeout.
- `GET /api/build/sessions/{id}/messages` returns `message_metadata`
  verbatim (already does).

## Open during phase

- Visual design: match existing message-card primitives; punt to
  design review during the phase.
- Truncation policy for `PayloadView` (proposed: ~300 chars body with
  "show more"; ~100 chars for inline fields like Linear description).

## Definition of done

- Inline card renders for `approval_request` with Approve / Reject
  buttons and the per-kind `PayloadView` for each of the three v0
  kinds.
- Clicking a button disables both immediately; on CONFLICT, the card
  refetches messages and the resolved row renders.
- A user who closes and reopens the chat within the request lifetime
  sees the persisted card and can act on it.
- An expired request renders the resolved card with disabled buttons
  on reload.
- Notification-stream refetch path works; polling fallback works when
  the notification stream is dropped.
- Playwright happy path green.
