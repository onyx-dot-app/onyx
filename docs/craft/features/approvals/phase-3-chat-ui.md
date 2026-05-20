# Phase 3 — Chat Approval UI (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2.

## Goal

Move the user's decision point from a notification deep link into the
chat itself. An inline approval card renders where the gated action is
happening, with Approve / Reject buttons. The card persists on the
conversation so a user returning later sees it.

When the request times out (sandbox-disconnect or proxy 180s), the card
shows its terminal state and the buttons are disabled.

## What changes

This phase is mostly frontend. The backend writes already happen in
Phase 2 (`service.create` writes a `BuildMessage`; `service.respond`
writes a resolution `BuildMessage`). Phase 3 makes them render.

If Phase 2 deferred the `BuildMessage` writes, they belong here.

## Backend changes (small)

If not done in Phase 2:

```python
# inside service.create (Phase 2 stub becomes real here)
msg = BuildMessage(
    session_id=session_id,
    type=MessageType.ASSISTANT,
    message_metadata={
        "type": "approval_request",
        "approval_id": str(approval_id),
        "kind": kind,
        "summary": summary,
        "payload": payload,
        "status": "pending",
    },
)
db.add(msg)
```

```python
# inside service.respond
msg = BuildMessage(
    session_id=session_id,
    type=MessageType.ASSISTANT,
    message_metadata={
        "type": "approval_resolved",
        "approval_id": str(approval_id),
        "decision": decision,
        "decided_by": str(user_id),
    },
)
db.add(msg)
```

The packet type lives in `message_metadata["type"]` — no new
`MessageType` enum value, no schema migration on `BuildMessage`.

Same approach for the expiration path: when `await_decision` times out,
it writes the `approval_resolved` message with `decision: "expired"`.

## Frontend changes

```
web/src/app/craft/components/
├── BuildMessageList.tsx                     # add branch in renderAgentMessage
├── ApprovalCard.tsx                         # new
└── ApprovalResolved.tsx                     # new (or inline in ApprovalCard)

web/src/app/craft/services/apiServices.ts    # add postApprovalDecision
web/src/lib/notifications/interfaces.ts      # add APPROVAL_REQUESTED to enum
```

### Custom renderer in BuildMessageList

In `web/src/app/craft/components/BuildMessageList.tsx`, in the existing
`renderAgentMessage` (or equivalent dispatcher around message
`message_metadata.type`), add:

```tsx
if (message.message_metadata?.type === "approval_request") {
  return <ApprovalCard message={message} />;
}
if (message.message_metadata?.type === "approval_resolved") {
  return <ApprovalResolved message={message} />;
}
```

Precedent for keying off `message_metadata.type`: `TodoListCard`,
`ToolCallPill` already do this.

### ApprovalCard component

```tsx
type ApprovalRequestMetadata = {
  type: "approval_request";
  approval_id: string;
  kind: string;       // "slack.send_message"
  summary: string;    // "send 'hello' to #engineering"
  payload: Record<string, unknown>;
  status: "pending";  // always "pending" at write time
};

export function ApprovalCard({ message }: { message: BuildMessage }) {
  const meta = message.message_metadata as ApprovalRequestMetadata;
  const [resolvedLocally, setResolvedLocally] = useState<string | null>(null);

  // If a sibling "approval_resolved" message has shown up in the message
  // list, that's also terminal — handled by ApprovalResolved branch.

  async function decide(decision: "approve" | "reject") {
    try {
      await postApprovalDecision(meta.approval_id, decision);
      setResolvedLocally(decision);
    } catch (e) {
      // CONFLICT → approval already decided (e.g., expired). Refetch
      // messages to pick up the resolved row and rerender.
      refetchMessages();
    }
  }

  if (resolvedLocally) {
    return <ApprovalResolved decision={resolvedLocally} />;
  }

  return (
    <Card>
      <CardHeader>{labelForKind(meta.kind)}</CardHeader>
      <CardBody>
        <p className="font-medium">{meta.summary}</p>
        <PayloadView payload={meta.payload} kind={meta.kind} />
      </CardBody>
      <CardActions>
        <Button onClick={() => decide("approve")}>Approve</Button>
        <Button variant="secondary" onClick={() => decide("reject")}>
          Reject
        </Button>
      </CardActions>
    </Card>
  );
}
```

`PayloadView` is a small per-kind renderer:
- `slack.send_message`: channel + message body.
- `linear.create_issue`: team + title + (collapsed) description.
- `gcal.create_event`: title + time + attendees.

Falls back to a JSON pretty-print for any kind it doesn't recognize.

### ApprovalResolved component

```tsx
export function ApprovalResolved({ decision, decided_by }) {
  const label = {
    approve: "Approved",
    reject: "Rejected",
    expired: "Timed out",
  }[decision] ?? decision;
  return (
    <SmallCard tone={decision === "approve" ? "success" : "muted"}>
      {label}{decided_by ? ` by ${decided_by}` : ""}
    </SmallCard>
  );
}
```

When rendered as a sibling to the original `approval_request`, the
existing card can hide itself or show the disposition inline — either
works. Recommendation: render only the resolved card when the resolved
sibling exists; otherwise the original card.

### API helper

```ts
// web/src/app/craft/services/apiServices.ts
export async function postApprovalDecision(
  approvalId: string,
  decision: "approve" | "reject",
): Promise<void> {
  const res = await fetch(`/build/approvals/${approvalId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!res.ok) {
    throw new ApiError(res);
  }
}
```

### Notification handling

`web/src/lib/notifications/interfaces.ts` — add `APPROVAL_REQUESTED` to
the enum. Also patch the existing missing `SCHEDULED_TASK_*` entries
while in the file.

In `NotificationsPopover.tsx` (already polls and re-renders), no logic
change — the new type appears with whatever default UI the popover
gives. Clicking a notification deep-links to the relevant session.

When the popover refreshes notifications, the chat tab for that session
should refetch messages so the new card appears. Two options:
- Subscribe the chat to the same notification stream and refetch when
  `APPROVAL_REQUESTED` arrives for the current session.
- Poll the chat's messages endpoint every N seconds while focused.

Recommended: the first option; pattern matches what the popover already
does.

## Testing

- **Playwright** (one happy path):
  - Trigger a gated action in a session.
  - Card appears inline within ~1s of the action firing.
  - Click Approve.
  - Action completes; resolved card replaces the original.
- **Component**:
  - `ApprovalCard` renders for each gated kind we ship.
  - Buttons disabled state on resolved.
  - Conflict-on-decision (e.g., approval already expired) refetches.

## Dependencies

- Phase 2 complete (service writes `BuildMessage` rows).
- `GET /build/sessions/{id}/messages` returns `message_metadata`
  verbatim (already does).

## Open during phase

- Visual design of the card — match existing message-card styling. Punt
  to design review during the phase.
- Whether to show the payload diff (e.g., full Slack message body) or
  truncate. Recommend truncate with a "show more" expander.

## Definition of done

- Inline card renders for `approval_request` messages.
- Approve / Reject buttons POST decisions and update the local view
  without a full page refresh.
- Reload-from-zero (close and reopen chat) renders the persisted card
  correctly.
- Resolved (or expired) approvals render in the terminal state.
- Notification → session refetch flow works.
- Playwright happy path green.
