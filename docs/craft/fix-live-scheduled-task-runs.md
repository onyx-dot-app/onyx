# Live Scheduled Task Run Viewing

## What

1. Let users open a scheduled task run while it is still running, instead of waiting for a terminal status.
2. Reuse the existing Craft session view as the run viewer; do not create a separate run-detail surface.
3. Prevent follow-up messages only while the scheduled run is still in flight. Once the run finishes, the user can continue the Craft session normally, including after `SUCCEEDED` or `FAILED`.
4. Keep queued and skipped runs non-openable when no Craft session exists yet.

## Important Notes

- The run history table already polls the newest page every 5 seconds and keeps older loaded pages stable.
- The frontend currently blocks `RUNNING` and `AWAITING_APPROVAL` rows even when the backend has linked a `session_id`.
- The scheduled-task executor already creates a `BuildSession`, writes the initial user prompt, links `ScheduledTaskRun.session_id`, and commits before driving the agent loop. That means a live session exists before completion.
- The session view currently loads saved messages once when opened. It does not attach to the executor's live event stream, and it does not know whether a scheduled-origin session is still actively being driven by the background executor.
- The current product doc explicitly says in-progress runs are not openable. This change should update that doc so the product contract matches the new behavior.

## Key Decisions

1. Use Redis-backed SSE as the live-viewing architecture. The scheduled-task executor should publish live session/run events keyed by `session_id` or `run_id`, and the API server should expose an SSE endpoint that browsers attach to while viewing an active scheduled run.

### Why Redis-backed SSE

- The scheduled executor runs in a Celery worker, while browsers connect to the web/API process. Redis gives both processes a shared fan-out layer without requiring the browser to connect to a worker process directly.
- SSE matches the interaction model: the viewer only needs server-to-browser updates while the scheduled run is active. There is no need for bidirectional control while the executor owns the run.
- Craft already has SSE-shaped frontend plumbing for streaming agent progress, so the viewer can reuse the same event parsing and session-store merge patterns instead of introducing a second real-time transport.
- Redis pub/sub avoids sticky routing problems. Any API server that receives the browser's SSE request can subscribe to the relevant Redis channel and forward events.
- The database remains the recovery path. On page load or reconnect, the session view hydrates from persisted messages, then resumes the SSE subscription for fresh events until the run reaches a terminal status.

### Other Options Considered

- Direct DB polling: simplest to build, but laggy and dependent on how frequently the executor flushes partial progress. It also creates repeated read load while the user watches a run.
- API-server-local in-memory fan-out: works only when the process driving the run and the process serving the browser are the same, which is not true for Celery workers and horizontally scaled API servers.
- WebSockets: useful for bidirectional control, but unnecessary here because the active run is executor-owned. It adds connection management complexity without clear product value for read-only live viewing.
- Durable event-log tailing: robust for replay and reconnects, but it requires a new persisted event model. That is heavier than needed if the canonical transcript remains in `BuildMessage` and Redis handles only live delivery.

## Implementation

1. Extend the scheduled-run context used by the Craft session view with the minimal run state needed by the viewer. The key extra field is run status, so the UI can tell `RUNNING` / `AWAITING_APPROVAL` from `SUCCEEDED` / `FAILED`; `finished_at` is useful for display and for stopping the live subscription; `run_id` is useful for subscribing to or invalidating one exact run.
2. Update the run history clickability rules so `RUNNING`, `FAILED`, `SUCCEEDED`, and `AWAITING_APPROVAL` runs are openable whenever they have a `session_id`. Keep `QUEUED` rows blocked until the executor creates the session, and keep `SKIPPED` rows blocked because no session is created.
3. Update the scheduled-run banner and Craft chat panel to make the in-flight state clear. Disable the normal chat input while the scheduled run is still being driven by the executor; re-enable the normal input once the run reaches a terminal state so the user can ask follow-up questions in the same session.
4. Add a live scheduled-session event path. The executor publishes progress events as it processes ACP events, the API server bridges those events to browser clients over SSE, and the frontend merges those events into the existing session store while preserving scroll behavior. Stop the live subscription once the run reaches a terminal state.
5. Make the executor's persisted progress good enough for recovery. Keep committing persisted tool progress, plans, and finalized message chunks during the run so page reloads and SSE reconnects can hydrate from durable state.
6. Preserve current boundaries: scheduled sessions stay out of the Craft sidebar, ownership checks continue to use the existing session and scheduled-task ownership paths, and all backend errors should use `OnyxError` when touching these APIs.
7. Update the scheduled-tasks product doc to remove the old "wait until complete" limitation and describe live viewing with follow-up messages available after the scheduled run finishes.

## Test cases

1. Verify a running scheduled run with a linked session can be opened from the task detail run history before it completes.
2. Verify queued runs without a session and skipped runs remain non-openable with clear disabled affordances.
3. Verify the live run view shows the scheduled-run banner, disables the normal chat input while the run is active, and receives live progress without a page reload.
4. Verify the live subscription stops or settles after the run reaches a terminal status, and the normal chat input is available again for follow-up messages.
5. Verify refreshing after the live subscription ends loads and uses the Postgres-based saved messages rather than Redis-delivered live events.
6. Verify a new message can be sent after the scheduled run finishes, and the response streams as a normal Craft follow-up.
7. Verify scheduled-origin sessions still do not appear in the normal Craft sidebar history.
8. Run the focused frontend type check and the relevant scheduled-task backend/API test slice.
