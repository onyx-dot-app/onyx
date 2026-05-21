# Phase 3 — Chat Approval UI (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2.

## Goal

Render an actionable Approve / Reject card inline in the chat for every
`approval_request` `BuildMessage` that the server reports as
`is_live=true`. When `is_live` flips false, the card disappears
entirely. The agent's next chat message is the only post-decision
artifact.

`is_live` is provided by the server on each `approval_request`
BuildMessage in the `GET /api/build/sessions/{id}/messages` response
(Phase 2 deliverable). The frontend treats it as authoritative and
re-reads it on every refetch.

## Module layout

All changes are frontend.

```
web/src/app/craft/components/
  BuildMessageList.tsx                       # new dispatch branch
  ApprovalCard.tsx                           # new
  PayloadView.tsx                            # new; per-action_type payload renderer
  actionLabels.ts                            # new; action_type → display string map

web/src/app/craft/services/apiServices.ts    # postApprovalDecision
web/src/app/craft/hooks/useApprovalPolling.ts  # new; fallback poller
web/src/lib/notifications/interfaces.ts      # APPROVAL_REQUESTED enum value
```

## Tasks

### T3.1 — Add a `message_metadata.type` dispatch path in `BuildMessageList`

`renderAgentMessage` today branches on whether `message.message_metadata?.streamItems`
is populated; otherwise it falls back to rendering `message.content` via
`TextChunk`.

Add `is_live?: boolean` to the `BuildMessage` TypeScript type
(`web/src/app/craft/types/streamingTypes.ts`) so the dispatch can read
it. Then add a top-of-function check in `renderAgentMessage` before
the existing `savedStreamItems` branch:

```tsx
const meta = message.message_metadata;
if (meta?.type === "approval_request") {
  if (!message.is_live) return null;
  return <ApprovalCard message={message} />;
}
```

The `is_live=false` branch returns `null` explicitly — the BuildMessage
row stays in the database for audit; the chat just doesn't render it.

### T3.2 — `ApprovalCard` component

Behavioral contract:

- Input: a `BuildMessage` whose `message_metadata` matches the
  `approval_request` shape from Phase 2 (`approval_id`,
  `action_type`, `payload`) and whose `is_live` is `true`. The
  dispatch in T3.1 guarantees this.
- Renders: a header string resolved from `actionLabels[action_type]`
  (e.g. `"Craft is trying to send a message in Slack"`),
  `<PayloadView>` for the structured payload, and Approve / Reject
  buttons.
- On Approve / Reject click: immediately disable both buttons (local
  state), then POST the decision via `postApprovalDecision`.
- On success: call `refetchMessages()`. The server will now report
  `is_live=false` and the dispatch in T3.1 stops rendering the card.
  Optimistic local hiding is acceptable as a latency optimization, but
  the refetch is the authoritative source.
- On CONFLICT (already decided or expired): same path — call
  `refetchMessages()`.

### T3.3 — `PayloadView` per-action_type renderers

Per-action_type rendering for the v0 action set:

- `slack.send_message` (Slack `chat.postMessage`): channel name and
  message body. Truncate the body at ~300 chars with a "show more"
  expander.
- `linear.create_issue` (Linear `IssueCreate`): team key, issue title,
  truncated description.
- `gcal.create_event` (GCal `events.insert`): event title, start time,
  attendee count.
- **Malformed-payload fallback for known action_types.** If a known
  `action_type` payload is missing fields the renderer expects (e.g.
  `slack.send_message` without `channel`), render the action label
  and fall through to the JSON pretty-print path with a small
  "Payload did not match expected shape" notice. Do not throw or
  render a blank card.
- **Fallback for unrecognized action_types**: render `action_type`
  verbatim as the header and JSON pretty-print of `payload`.

### T3.4 — `postApprovalDecision` helper

Add to `apiServices.ts`, mirroring the existing fetch conventions in
that file (`/api/build/...` rewrite path, no explicit `credentials`,
JSON content type, throw on non-OK). Signature:

```ts
async function postApprovalDecision(
  approvalId: string,
  decision: "approve" | "reject",
): Promise<void>
```

On 409 CONFLICT, throw an `ApprovalConflictError` the card can catch
distinctly from generic errors. The caller (the card) calls
`refetchMessages` on success.

### T3.5 — Triggers that refresh `is_live`

Three paths can flip a card from `is_live=true` to `is_live=false`,
in order from fastest to slowest:

1. **Message-stream-triggered refetch (primary).** The chat's existing
   real-time message stream delivers new assistant messages as the
   agent emits them. When the sandbox's HTTP call times out or fails,
   the agent's very next message is a tool-call result — and at that
   moment the underlying request has resolved (the proxy has already
   written EXPIRED / REJECTED). In the stream's `onmessage` handler,
   when a new assistant `BuildMessage` arrives for a session that has
   at least one visible `approval_request` card with `is_live=true`,
   call `refetchMessages` for that session. The same refetch that
   appends the new tool-call message re-evaluates `is_live` for
   prior approval cards — card disappears at the same instant the
   tool result renders.

2. **Notification stream.** Add `APPROVAL_REQUESTED` to
   `web/src/lib/notifications/interfaces.ts`. When the chat is open
   on the targeted session and a notification of this type arrives,
   call `refetchMessages`. This is mostly relevant for the initial
   appearance of the card; decisions don't fire notifications.

3. **Polling fallback.** SSE / notification streams can drop without
   the user noticing. Add `useApprovalPolling(sessionId)` modeled on
   the existing `usePreProvisionPolling` hook (same `setInterval` +
   `isCheckingRef` + try/catch + cleanup shape). Cadence 10s; polls
   `GET /api/build/sessions/{sessionId}/messages` while the session
   has at least one visible `approval_request` BuildMessage with
   `is_live=true`. Stops naturally when no cards are visible.

The popover itself needs no logic change for v0; `APPROVAL_REQUESTED`
notifications render with default UI and deep-link to the session.

## Testing

- **Playwright (happy path).** Stand-in sandbox triggers a gated
  request, card appears inline within ~1s of the proxy hitting the
  service, click Approve, assert the card disappears once the
  messages refetch reports `is_live=false`, and the upstream action
  completes.
- **Playwright (Reject).** Same shape; assert the agent receives the
  rejection and reports the failure in its next message.
- **Playwright (reload).** Trigger a gated request, reload the chat,
  assert the card is still actionable.
- **Playwright (sandbox-side timeout).** Trigger a gated request,
  let the sandbox's HTTP client time out before the proxy's 180s
  wait; assert the agent's next tool-result message appears AND
  the approval card disappears at the same instant — no window
  where both are visible together.

Component tests are out of scope for Phase 3 — Playwright covers the
end-to-end paths and bespoke mocks for `refetchMessages` add fragility
without commensurate coverage. No backend tests in this phase.

## Dependencies

- Phase 2 merged: `approval_request` `BuildMessage` written by the
  gate addon at request-create time; `is_live: bool` field returned
  on every `approval_request` BuildMessage from
  `GET /api/build/sessions/{id}/messages`, computed server-side as
  `approval.decision is None AND cache.exists(approval:live:{id})`
  and cached for 5s.
- `GET /api/build/sessions/{id}/messages` returns `message_metadata`
  verbatim (already does), plus the new `is_live` field per approval
  card.

## Open during phase

- Visual design: match existing message-card primitives; punt to
  design review during the phase.
- Truncation policy for `PayloadView` (proposed: ~300 chars body with
  "show more"; ~100 chars for inline fields like Linear description).

## Definition of done

- Actionable card renders inline for every `approval_request`
  BuildMessage with `is_live=true`, including the per-action_type
  `PayloadView` for each of the three v0 kinds.
- Clicking Approve or Reject disables both buttons immediately, posts
  the decision, and the card disappears once the messages response
  reports `is_live=false`.
- On CONFLICT, the card triggers a refetch and disappears.
- A user who reloads while a card is `is_live=true` sees the same
  actionable card and can act on it.
- Message-stream-triggered refetch fires when a new assistant
  message arrives in a session with a visible approval card —
  card disappears at the same instant the tool-result renders, no
  visible mid-state where both are shown.
- Notification-stream refetch path works on initial appearance;
  polling fallback works when streams drop, and polling stops
  naturally once no `is_live=true` cards remain.
- Playwright happy path green.
