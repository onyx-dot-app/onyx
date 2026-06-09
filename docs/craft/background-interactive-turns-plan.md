# Background Interactive Turns Plan

## Issues to Address

Interactive Craft turns were request-bound: `POST /sessions/{id}/send-message`
owned the generator that drove opencode, persisted packets, and released the
prompt slot. A browser refresh closed that stream, causing `GeneratorExit` to
abort the sandbox turn and drop the live UI.

The target shape is to split starting work from watching work:

- `POST /sessions/{id}/send-message` creates one interactive turn and returns
  turn metadata.
- A backend runner drives the sandbox opencode session and persists packets.
- `GET /sessions/{id}/turns/{turn_id}/events` attaches to the live sandbox
  event stream without owning the turn.
- The frontend reloads saved messages, asks for an active turn, and attaches
  instead of resending the prompt.

## Important Notes

- No DB migration should be required. Active turn state can live in
  `CacheBackend` with TTLs, request idempotency, runner ownership, and
  heartbeat/stale-claim recovery.
- Scheduled runs are the closest existing pattern: the runner owns the prompt
  and persistence loop, while the UI can attach to the sandbox pod's opencode
  `/event` stream as a viewer.
- The long-running agent session still happens inside the sandbox pod. The API
  runner is responsible for draining that session, applying interrupt fencing,
  and committing durable `BuildMessage` rows.
- Redis-backed state is required for cross-pod visibility. In-memory caches
  are not acceptable for active turns, runner ownership, or attach/rejoin.
- The top-level parent-turn foreground path should be removed once the turns
  API owns parent interactive turns. Lower-level sandbox `send_message` remains
  the opencode transport primitive and subagent follow-ups may still stream
  directly.

## Implementation Strategy

1. Add a CacheBackend-backed interactive turn lifecycle:
   `QUEUED`, `RUNNING`, terminal statuses, active-turn lookup by session, and
   idempotency by `client_request_id`.
2. Change `POST /send-message` to validate ownership, persist the user message,
   create the turn, start/retry a background runner, and return JSON turn
   metadata instead of an SSE response.
3. Build the runner from existing session pieces: `prompt_slot`,
   `yield_sandbox_events`, `merge_events_with_announces`,
   `persist_sandbox_event`, `finalize_persist`, interrupt fence checks, and
   heartbeat updates.
4. Add attach-only APIs:
   - `GET /turns/active` for refresh/rejoin discovery.
   - `GET /turns/{turn_id}/events` for live SSE viewing through
     `subscribe_to_existing_session_events`.
5. Update the frontend to track `activeTurnId` and local ownership, call
   `createTurn`, attach with `streamTurnEvents`, and reattach from
   `loadSession` when the session has a running active turn.
6. Delete deprecated parent-turn request-bound code paths and avoid preserving
   compatibility tests for the removed stream owner.

## Tests

- Unit tests for CacheBackend turn state: idempotency, single active turn,
  terminal cleanup, runner claiming, stale reclaim, and queued requeue.
- Unit tests for runner behavior: persistence, prompt slot conflict,
  sandbox errors, missing final response, and ownership loss.
- API tests for `send-message`, active-turn lookup, attach-only stream
  behavior, terminal errors, and stale/not-running turns.
- Sandbox transport tests for transient opencode `/event` reconnects and
  coalesced live text bursts.
- Frontend hook/store tests for `createTurn` + attach, refresh rejoin,
  attach failures, in-band errors, and stale terminal turn handling.
- Integration or local smoke tests through `localhost:3000` to confirm
  refresh/rejoin does not resend the prompt and the UI displays streamed
  output from the still-running sandbox session.
