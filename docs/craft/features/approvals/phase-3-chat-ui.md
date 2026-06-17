# Phase 3 — Chat Approval UI (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2.

## Goal

Render an actionable Approve / Reject card at the bottom of the chat
for every currently-live approval request on the open session. The
card list is owned by a SWR-cached fetch of a dedicated endpoint that
returns only undecided, in-flight requests; the card disappears on
the next revalidation as soon as the user resolves it or the server
expires it. The agent's subsequent tool-call `BuildMessage` is the
only permanent record of the action's outcome.

The `BuildMessage` stream is not a carrier for approvals: there is no
`is_live` flag on `MessageResponse` and no dispatch on
`message_metadata.type`. The chat's saved-message rendering path is
untouched. Approval visibility is driven entirely by the `/live`
endpoint plus SWR cache invalidation triggered by a dedicated SSE
packet on the open chat stream (see T3.6).

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
`is_live === true`. The server defines "live" as a SQL window:
`decision IS NULL AND created_at >= now() - WAIT_TIMEOUT_S` (180s),
so orphan rows from a hard proxy crash drop off the list once the
window passes.

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

### `approval_requested` SSE packet

The chat-streaming endpoint emits a dedicated packet on the open SSE
stream when a new approval is committed by the proxy:

```ts
interface ApprovalRequestedPacket {
  type: "approval_requested";
  approval_id: string;   // UUID
  session_id: string;    // UUID
  timestamp: string;     // ISO datetime
}
```

`parsePacket` maps this to a `ParsedApprovalRequested` with camelCase
fields (`approvalId`, `sessionId`) in the discriminated union. The
packet carries no row data — it is purely an invalidation signal
telling the FE to refetch `/live`.

Mechanically, the proxy `RPUSH`es the approval id onto
`approval:announce:{session_id}` after committing the row to
Postgres. The session manager's `_merge_acp_with_announces` `BLPOP`s
that list (1s timeout) on every active chat-streaming request and
emits one `ApprovalRequestedPacket` per popped id. Worst-case latency
from proxy commit to card render is ~1–2s (1s BLPOP timeout +
network + SWR fetch).

## Module layout

All changes are frontend.

```
web/src/app/craft/components/
  LiveApprovalsRegion.tsx                       # new; bottom-of-chat container
  ApprovalCard.tsx                              # new; single Approve / Reject card
  PayloadView.tsx                               # new; per-action_type payload renderer
  actionLabels.ts                               # new; action_type → display string

web/src/app/craft/hooks/useLiveApprovals.ts     # new; SWR wrapper around fetchLiveApprovals
web/src/app/craft/services/apiServices.ts       # add fetchLiveApprovals, postApprovalDecision
```

No changes to `useBuildStreaming.ts` are owned by Phase 3 — the
`approval_requested` case there ships alongside the SSE merger
(Phase 2 / streaming work) and already calls
`globalMutate(SWR_KEYS.buildSessionLiveApprovals(sessionId))`. Phase
3 consumes that signal via the SWR cache key.

## Tasks

### T3.1 — `LiveApprovalsRegion` at the bottom of the chat

`LiveApprovalsRegion` is rendered by the chat page directly below
`BuildMessageList`, inside the same scrollable container, styled to
match an assistant message region (logo + left margin). It calls
`useLiveApprovals(sessionId)` and renders one `ApprovalCard` per
returned item in `created_at` order.

`useLiveApprovals` is a thin SWR wrapper:

```ts
export function useLiveApprovals(sessionId: string) {
  return useSWR<ApprovalListResponse>(
    SWR_KEYS.buildSessionLiveApprovals(sessionId),
    fetcher,
  );
}
```

Because every component that needs to invalidate the list shares the
same SWR key, no `refetchLiveApprovals` callback is plumbed through
props or context. Anything with access to `useSWRConfig`'s
`globalMutate` can trigger a revalidation by mutating
`SWR_KEYS.buildSessionLiveApprovals(sessionId)`. The card list is
always whatever the latest `/live` response said it was — the server
is the authority on what's live.

When the response has zero items the region renders nothing (no empty
state, no placeholder).

### T3.2 — `ApprovalCard` component

Props: an `ApprovalView`. The card uses `useSWRConfig`'s `mutate` to
invalidate `SWR_KEYS.buildSessionLiveApprovals(sessionId)` directly;
no callback is passed in.

Renders:

- A header string resolved from `actionLabels[action_type]`
  (e.g. `"Craft is trying to send a message in Slack"`).
- `<PayloadView action_type={...} payload={...} />` for the structured
  payload.
- Approve and Reject buttons, side by side.

Behavior:

- Click Approve or Reject → set local `submitting=true` to disable
  both buttons, then `await postApprovalDecision(approval_id, "APPROVED" | "REJECTED")`.
- On success (200) → `mutate(SWR_KEYS.buildSessionLiveApprovals(sessionId))`.
  The `/live` endpoint will no longer return this row, so the card
  unmounts on the next render. Optimistic local removal (mutating
  the cached `ApprovalListResponse` to drop the row before the
  refetch resolves) is acceptable but not required.
- On 409 CONFLICT (decided by someone else / expired by the proxy) →
  same path: revalidate the SWR key and unmount.
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
): Promise<ApprovalListResponse> {
  const res = await fetch(
    `${API_BASE}/approvals/sessions/${sessionId}/live`,
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch live approvals: ${res.status}`);
  }
  return res.json();
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
from generic network errors and route both into the same SWR
revalidation path while keeping logs clean.

### T3.6 — Refresh triggers

There is no polling timer and no per-component event subscription.
Everything that needs to change the card list does so by mutating one
SWR key.

1. **SSE-piggyback (new card appears).** `useBuildStreaming` already
   handles `approval_requested` packets on the open chat stream:

   ```ts
   case "approval_requested": {
     void globalMutate(SWR_KEYS.buildSessionLiveApprovals(sessionId));
     break;
   }
   ```

   When the proxy commits an approval row, the session manager pops
   the announce id and emits the packet on whatever chat stream is
   currently open for that session. The mutate call invalidates the
   SWR cache; `useLiveApprovals` refetches; the new row arrives in
   the next response and the card mounts. Worst-case latency from
   proxy commit to card render is ~1–2s.

2. **Local mutate (decision submitted).** The card itself calls
   `mutate(SWR_KEYS.buildSessionLiveApprovals(sessionId))` after a
   200 or 409 from `POST /decision` (see T3.2). The row is gone from
   `/live` by the time the refetch resolves, so the card unmounts.

3. **Reconnect / remount.** The SSE stream does not replay history on
   reconnect. If a user reloads the page or navigates back into a
   session with a pending approval, the SWR mount on
   `LiveApprovalsRegion` triggers a fresh `/live` fetch and the card
   re-renders with no event needed. SWR's `revalidateOnFocus` and
   `revalidateOnReconnect` defaults also cover tab-refocus and
   network-recovery cases without any custom code.

No polling timer is required. The Phase 2 design replaced the Redis
liveness key with a SQL `created_at` window, and the SSE merger
ensures the FE learns about new approvals as soon as the chat stream
is open. A user without an open chat stream cannot see a card
appear, but cannot act on one either — the card surface lives inside
the chat.

`APPROVAL_REQUESTED` notifications are still emitted server-side by
the gate addon as an out-of-chat signal (badge / popover), but the
card hook does not depend on them. The notifications popover requires
no logic change for v0; the notification renders with the default UI
and deep-links to the session, where the SWR mount on the chat page
takes over.

## Testing

Playwright end-to-end tests only.

- **Happy path.** Stand-in sandbox triggers a gated request, card
  appears at the bottom of the chat within ~1–2s of the proxy
  commit (BLPOP wake + SSE packet + SWR refetch), click Approve, the
  card unmounts after the post-decision revalidation, the agent's
  next tool-call message reports success.
- **Reject.** Same shape; assert the agent's next message reports the
  failure.
- **Reload mid-decision.** Trigger a gated request, reload the chat,
  the card is still rendered and still actionable. This exercises
  the SWR mount path — the SSE stream re-opens but does not replay
  the `approval_requested` packet, so the card has to come from the
  fresh `/live` fetch alone.
- **Sandbox-side timeout.** Trigger a gated request, let the sandbox's
  HTTP client time out before the proxy's 180s wait; once the
  `created_at + WAIT_TIMEOUT_S` window passes, the next revalidation
  of `/live` (e.g. on tab focus, navigation, or a subsequent
  `approval_requested` packet) drops the card. The agent's next
  tool-result message reports the timeout. The card and the
  tool-result message are not guaranteed to render in the same
  frame — assert that the card is gone by the time the test waits on
  the tool-result message, not before.

Component tests are out of scope for Phase 3. No backend tests in
this phase.

## Dependencies

- Phase 2 merged: `ActionApproval` rows persisted by the gate addon
  at request-create time, `/api/build/approvals/sessions/{id}/live`
  filtering on the SQL `created_at` window, and
  `/api/build/approvals/{id}/decision` exposed under the `/build`
  prefix with `BASIC_ACCESS` and Craft-enabled checks.
- SSE-piggyback shipped: `ApprovalRequestedPacket` defined in
  `backend/onyx/server/features/build/packets.py`,
  `_merge_acp_with_announces` in the session manager `BLPOP`ing the
  `approval:announce:{session_id}` list and emitting the packet on
  the chat stream, `parsePacket` handling the `approval_requested`
  case, and `useBuildStreaming` mutating
  `SWR_KEYS.buildSessionLiveApprovals(sessionId)` on receipt.
- `APPROVAL_REQUESTED` notifications still emitted server-side at
  request-create time as a best-effort out-of-chat signal, scoped to
  the session owner. Not required for card surfacing.

## Open during phase

- Visual design of `LiveApprovalsRegion` and `ApprovalCard`: match
  existing assistant message and pill primitives; punt to design
  review during the phase.
- Truncation policy for `PayloadView` (proposed: ~300 chars for the
  Slack body with a "show more" expander).

## Definition of done

- `LiveApprovalsRegion` renders at the bottom of the chat and shows
  one `ApprovalCard` per item returned by
  `GET /api/build/approvals/sessions/{id}/live`, sourced via
  `useLiveApprovals` (a SWR wrapper on
  `SWR_KEYS.buildSessionLiveApprovals(sessionId)`).
- Each card renders the resolved action label and a `PayloadView` for
  its `action_type`, with the malformed-payload fallback in place for
  known types and the verbatim + JSON fallback for unknown types.
- Clicking Approve or Reject disables both buttons, posts the
  decision, mutates the SWR key, and the card disappears on the
  next revalidation.
- 409 CONFLICT is treated as a successful resolution: the card
  mutates the SWR key and unmounts.
- A user who reloads while a card is live sees the same actionable
  card and can act on it — the SWR mount fetches `/live` without
  needing an SSE event.
- A new approval committed by the proxy while the chat stream is open
  surfaces a card within ~1–2s, driven by the
  `approval_requested` SSE packet's `globalMutate` on the shared SWR
  key.
- No polling timer ships with this phase; no heartbeat or
  liveness-flag check is required on the FE.
- Playwright happy path, reject, reload, and sandbox-timeout tests
  green.
