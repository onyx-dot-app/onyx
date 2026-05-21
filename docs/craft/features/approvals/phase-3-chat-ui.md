# Phase 3 — Chat Approval UI (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2.

## Goal

Render an actionable Approve / Reject card at the bottom of the chat
for every currently-live approval request on the open session. The
chat fetches live approvals from a dedicated endpoint that returns
only undecided, in-flight requests; the card disappears from the next
refetch onward as soon as the user resolves it or the server expires
it. The agent's subsequent tool-call `BuildMessage` is the only
permanent record of the action's outcome.

The `BuildMessage` stream is not a carrier for approvals: there is no
`is_live` flag on `MessageResponse` and no dispatch on
`message_metadata.type`. The chat's saved-message rendering path is
untouched.

## Backend contract consumed

Phase 3 consumes the approvals API mounted under `/api/build/approvals`.

`GET /api/build/approvals/sessions/{session_id}/live` returns the
session's currently-actionable approvals:

```ts
interface ApprovalView {
  approval_id: string;         // UUID
  session_id: string;          // UUID
  action_type: string;         // e.g. "slack.send_message"
  payload: Record<string, unknown>;
  created_at: string;          // ISO datetime
  decision: ApprovalDecision | null;
  decided_at: string | null;   // ISO datetime
  is_live: boolean;
}

interface ApprovalListResponse {
  items: ApprovalView[];
}
```

On the `/live` endpoint every returned row has `decision === null` and
`is_live === true` — the server filters server-side using a Redis
liveness key, so orphan rows from a hard proxy crash are excluded.

`POST /api/build/approvals/{approval_id}/decision` with body
`{decision: "APPROVED" | "REJECTED"}` records the user's decision and
returns the updated `ApprovalView`. On a competing decision the server
responds 409 with the standard `OnyxError` shape
`{error_code: "CONFLICT", detail: "..."}`. Same-value re-submits are
idempotent and return 200.

```ts
type ApprovalDecision = "APPROVED" | "REJECTED" | "EXPIRED";

interface DecisionBody {
  decision: "APPROVED" | "REJECTED";   // EXPIRED is server-only
}
```

## Module layout

All changes are frontend.

```
web/src/app/craft/components/
  LiveApprovalsRegion.tsx                       # new; bottom-of-chat container
  ApprovalCard.tsx                              # new; single Approve / Reject card
  PayloadView.tsx                               # new; per-action_type payload renderer
  actionLabels.ts                               # new; action_type → display string

web/src/app/craft/services/apiServices.ts       # add fetchLiveApprovals, postApprovalDecision
web/src/app/craft/hooks/useLiveApprovalsPolling.ts  # new; fallback poller
web/src/lib/notifications/interfaces.ts         # APPROVAL_REQUESTED enum value
```

## Tasks

### T3.1 — `LiveApprovalsRegion` at the bottom of the chat

`LiveApprovalsRegion` is rendered by the chat page directly below
`BuildMessageList`, inside the same scrollable container, styled to
match an assistant message region (logo + left margin). It holds the
`ApprovalView[]` state for the open session and renders one
`ApprovalCard` per item in `created_at` order.

The region is the single owner of `fetchLiveApprovals(sessionId)`:

- Calls it on mount.
- Exposes a stable `refetchLiveApprovals()` callback (via context or
  prop drilling from the chat shell) so the message stream,
  notification stream, and polling hook can all trigger a refresh.
- Replaces local state with the response on every refetch — server is
  the authority on what's live.

When the response has zero items the region renders nothing (no empty
state, no placeholder).

### T3.2 — `ApprovalCard` component

Props: an `ApprovalView` and a `refetchLiveApprovals` callback.

Renders:

- A header string resolved from `actionLabels[action_type]`
  (e.g. `"Craft is trying to send a message in Slack"`).
- `<PayloadView action_type={...} payload={...} />` for the structured
  payload.
- Approve and Reject buttons, side by side.

Behavior:

- Click Approve or Reject → set local `submitting=true` to disable
  both buttons, then `await postApprovalDecision(approval_id, "APPROVED" | "REJECTED")`.
- On success (200) → call `refetchLiveApprovals()`. The `/live`
  endpoint will no longer return this row, so the card unmounts on
  the next render.
- On 409 CONFLICT (decided by someone else / expired by the proxy) →
  same path: call `refetchLiveApprovals()` and unmount.
- On any other error → re-enable the buttons and surface an inline
  error string under the buttons.

The card never holds post-decision UI. The user's signal that their
action took effect is the agent's next tool-call `BuildMessage`
arriving in the chat above.

### T3.3 — `PayloadView` per-action_type renderers

Per-action_type rendering for the v0 action set:

- `slack.send_message` (Slack `chat.postMessage`): channel name and
  message body. Truncate the body at ~300 chars with a "show more"
  expander.

For known action_types whose payload is missing expected fields
(e.g. `slack.send_message` without `channel`): render the resolved
action label, JSON-pretty-print the payload, and show a small
"Payload did not match expected shape" notice. The renderer never
throws.

For unrecognized action_types: render `action_type` verbatim as the
header and JSON-pretty-print of `payload`.

### T3.4 — `actionLabels.ts`

Maps `action_type` → display string. Examples:

```ts
export const actionLabels: Record<string, string> = {
  "slack.send_message": "Craft is trying to send a message in Slack",
};

export function resolveActionLabel(actionType: string): string {
  return actionLabels[actionType] ?? actionType;
}
```

Unknown keys fall back to the verbatim `action_type`.

### T3.5 — `apiServices.ts` additions

Mirror the existing fetch conventions in that file (`/api/build/...`
rewrite path, JSON content type, throw on non-OK).

```ts
export async function fetchLiveApprovals(
  sessionId: string,
): Promise<ApprovalView[]> {
  const res = await fetch(
    `${API_BASE}/approvals/sessions/${sessionId}/live`,
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch live approvals: ${res.status}`);
  }
  const data: ApprovalListResponse = await res.json();
  return data.items;
}

export class ApprovalConflictError extends Error {
  public readonly statusCode: number = 409;
  constructor(detail: string) {
    super(detail);
    this.name = "ApprovalConflictError";
  }
}

export async function postApprovalDecision(
  approvalId: string,
  decision: "APPROVED" | "REJECTED",
): Promise<ApprovalView> {
  const res = await fetch(
    `${API_BASE}/approvals/${approvalId}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    },
  );
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    throw new ApprovalConflictError(body.detail ?? "decision conflict");
  }
  if (!res.ok) {
    throw new Error(`Failed to post approval decision: ${res.status}`);
  }
  return res.json();
}
```

`ApprovalConflictError` lets the card distinguish "already resolved"
from generic network errors and route both into the same
`refetchLiveApprovals()` path while keeping logs clean.

### T3.6 — Refresh triggers

Three triggers can flip a card from visible to gone, fastest to
slowest:

1. **Message-stream-triggered refetch (primary).** The chat's existing
   SSE message stream delivers new assistant messages as the agent
   emits them. In the stream's `onmessage` handler, when a new
   assistant `BuildMessage` arrives for the open session and at least
   one approval card is currently visible, call
   `refetchLiveApprovals(sessionId)`. The /live endpoint re-evaluates
   liveness against Redis; resolved or expired requests drop off in
   the same tick that the tool-result message renders.

2. **Notification stream.** Add `APPROVAL_REQUESTED` to
   `web/src/lib/notifications/interfaces.ts`. When a notification of
   this type arrives for the open session, call
   `refetchLiveApprovals(sessionId)`. This is the path that surfaces
   the initial appearance of a new card; decisions don't fire
   notifications.

3. **Polling fallback.** SSE and notification streams can drop without
   the user noticing. `useLiveApprovalsPolling(sessionId)` is modeled
   on the existing `usePreProvisionPolling` hook (same `setInterval`
   + `isCheckingRef` + try/catch + cleanup shape). Cadence: 10s. It
   polls `fetchLiveApprovals(sessionId)` while the chat is open and
   the session is active, and stops on cleanup when the chat closes.

The notifications popover requires no logic change for v0;
`APPROVAL_REQUESTED` renders with the default UI and deep-links to
the session.

## Testing

Playwright end-to-end tests only.

- **Happy path.** Stand-in sandbox triggers a gated request, card
  appears at the bottom of the chat within ~1s, click Approve, card
  disappears on the next refetch, the agent's next tool-call message
  reports success.
- **Reject.** Same shape; assert the agent's next message reports the
  failure.
- **Reload mid-decision.** Trigger a gated request, reload the chat,
  the card is still rendered and still actionable.
- **Sandbox-side timeout.** Trigger a gated request, let the sandbox's
  HTTP client time out before the proxy's 180s wait; the agent's next
  tool-result message and the disappearance of the card render in the
  same frame, with no window where both are visible together.

Component tests are out of scope for Phase 3. No backend tests in
this phase.

## Dependencies

- Phase 2 merged: `ActionApproval` rows persisted by the gate addon
  at request-create time, Redis liveness key set for the duration of
  the proxy wait, `/api/build/approvals/sessions/{id}/live` and
  `/api/build/approvals/{id}/decision` endpoints exposed under the
  `/build` prefix with `BASIC_ACCESS` and Craft-enabled checks.
- `APPROVAL_REQUESTED` notifications emitted server-side at
  request-create time, scoped to the session owner.

## Open during phase

- Visual design of `LiveApprovalsRegion` and `ApprovalCard`: match
  existing assistant message and pill primitives; punt to design
  review during the phase.
- Truncation policy for `PayloadView` (proposed: ~300 chars for the
  Slack body with a "show more" expander).

## Definition of done

- `LiveApprovalsRegion` renders at the bottom of the chat and shows
  one `ApprovalCard` per item returned by
  `GET /api/build/approvals/sessions/{id}/live`.
- Each card renders the resolved action label and a `PayloadView` for
  its `action_type`, with the malformed-payload fallback in place for
  known types and the verbatim + JSON fallback for unknown types.
- Clicking Approve or Reject disables both buttons, posts the
  decision, and the card disappears on the next refetch.
- 409 CONFLICT is treated as a successful resolution: the card
  refetches and unmounts.
- A user who reloads while a card is live sees the same actionable
  card and can act on it.
- Message-stream-triggered refetch fires when a new assistant message
  arrives in a session with a visible approval card — the card
  disappears at the same instant the tool-result renders, with no
  visible mid-state.
- Notification-stream refetch surfaces newly-created cards;
  `useLiveApprovalsPolling` is the safety net when streams drop and
  stops on chat close.
- Playwright happy path, reject, reload, and sandbox-timeout tests
  green.
