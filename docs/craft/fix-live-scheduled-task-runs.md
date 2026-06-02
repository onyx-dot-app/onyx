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

1. Use an api-server SSE endpoint that proxies opencode-serve `/event` directly as the live-viewing architecture. Given a scheduled-run `session_id`, the api-server should resolve the sandbox pod, open the pod's `/event` stream with the existing auth path, filter events for that session, and stream matching ACP events to the browser.

### Why Direct opencode `/event` Proxying

- opencode-serve already emits the live event stream. The scheduled run differs from the interactive path because Celery is driving the prompt, not because the underlying live source changed.
- This keeps one source of truth for live progress: the sandbox pod's opencode `/event` stream. The api-server only attaches as another viewer and filters by session.
- It avoids adding Redis as a new live transport when the api-server can already reach sandbox pods. Redis would be justified if that network assumption is expected to go away, but it is extra infrastructure otherwise.
- The scheduled-task worker stays focused on running the job and persisting durable messages. It does not need to publish live events to another bus.
- The database remains the recovery path. On page load or reconnect, the session view hydrates from persisted messages, then resumes the direct SSE subscription for fresh events until the run reaches a terminal status.

### Other Options Considered

- Reuse `PodEventBus` inside the api-server: more efficient for multiple viewers because each api-server replica would hold one upstream `/event` connection per pod, then fan out locally. This is a good optimization if concurrent viewing becomes common, but the direct proxy is simpler for the first version.
- Redis-backed SSE: decouples api-server reachability from sandbox pod networking, which would matter for cross-cluster api-server, serverless api-server, or edge-routed api-server deployments. If api-server-to-pod reachability remains durable, Redis is heavier than needed.
- Browser-to-opencode tunnel: tempting because it is thin, but `/event` is pod-wide rather than session-scoped. The server must filter events before they reach the browser, which brings the design back to an api-server proxy.
- Direct DB polling: simplest to build, but laggy and dependent on how frequently the executor flushes partial progress. It also creates repeated read load while the user watches a run.

## Implementation

1. Extend the scheduled-run context used by the Craft session view with the minimal run state needed by the viewer. The key extra field is run status, so the UI can tell `RUNNING` / `AWAITING_APPROVAL` from `SUCCEEDED` / `FAILED`; `finished_at` is useful for display and for stopping the live subscription; `run_id` is useful for subscribing to or invalidating one exact run.
2. Update the run history clickability rules so `RUNNING`, `FAILED`, `SUCCEEDED`, and `AWAITING_APPROVAL` runs are openable whenever they have a `session_id`. Keep `QUEUED` rows blocked until the executor creates the session, and keep `SKIPPED` rows blocked because no session is created.
3. Update the scheduled-run banner and Craft chat panel to make the in-flight state clear. Disable the normal chat input while the scheduled run is still being driven by the executor; re-enable the normal input once the run reaches a terminal state so the user can ask follow-up questions in the same session.
4. Add a live scheduled-session event path on the api-server. Given a scheduled-run session, verify ownership, resolve the sandbox pod, open opencode-serve `/event`, filter events by the session id, and stream matching events to the browser over SSE. The frontend merges those events into the existing session store while preserving scroll behavior. Stop the live subscription once the run reaches a terminal state.
5. Make the executor's persisted progress good enough for recovery. Keep committing persisted tool progress, plans, and finalized message chunks during the run so page reloads and SSE reconnects can hydrate from durable state.
6. Preserve current boundaries: scheduled sessions stay out of the Craft sidebar, ownership checks continue to use the existing session and scheduled-task ownership paths, and all backend errors should use `OnyxError` when touching these APIs.
7. Update the scheduled-tasks product doc to remove the old "wait until complete" limitation and describe live viewing with follow-up messages available after the scheduled run finishes.

## Test cases

1. Verify a running scheduled run with a linked session can be opened from the task detail run history before it completes.
2. Verify queued runs without a session and skipped runs remain non-openable with clear disabled affordances.
3. Verify the live run view shows the scheduled-run banner, disables the normal chat input while the run is active, and receives live progress without a page reload.
4. Verify the live subscription stops or settles after the run reaches a terminal status, and the normal chat input is available again for follow-up messages.
5. Verify refreshing after the live subscription ends loads and uses the Postgres-based saved messages rather than the live opencode event stream.
6. Verify a new message can be sent after the scheduled run finishes, and the response streams as a normal Craft follow-up.
7. Verify scheduled-origin sessions still do not appear in the normal Craft sidebar history.
8. Run the focused frontend type check and the relevant scheduled-task backend/API test slice.
