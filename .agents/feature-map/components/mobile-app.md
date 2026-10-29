# Mobile App

> The React Native and Expo client, and the bearer-token auth gateway it signs
> in through. It is a second client of the chat backend, built apart from the
> web chat frontend, with its own copy of the stream parser and packet enum.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

A user installs a development build, enters the URL of an Onyx instance, and
signs in with email and password or with Google in the system browser. Other
SSO providers (OIDC, SAML) have no mobile sign-in.

The user can then:
- start a chat or open a past session from the sidebar, and open a project;
- pick an agent and a model, attach a document or a photo from the library,
  turn on deep research, force a tool, and turn tools and sources on or off;
- watch the answer stream, open its citations in a sources sheet, and stop
  the answer.

A tool disabled on mobile is also disabled on web, because the server saves
the setting per agent. The forced tool, the deep-research switch and the
source selection stay on the device.

The user cannot regenerate or edit a message, give feedback, compare models,
use voice, or take a photo with the camera. Tool activity (search, code,
image generation, deep research, memory) shows as an empty step in the
timeline. Only the answer text and reasoning render.

After an answer ends, Send stays disabled until the server confirms that the
session is idle. A send that the server does not accept keeps its draft.

On failure: a stream error shows in the message. A failed token refresh signs
the user out only when the server rejects the token. A network failure keeps
the session. When the user switches instance, the app never shows data or
uses a token from the previous instance.

---

## Scope

This component holds the mobile app and the mobile auth gateway on the
backend: bearer login, refresh and logout, and the Google sign-in hand-off
through a one-time code. The mobile standards file holds the coding rules
(see Architecture).

The backend endpoints the app calls belong to their own components:
[[core-chat-loop]], [[chat-persistence]], [[agents-personas]], [[projects]] and
[[auth-and-identity]]. The packet contract belongs to [[streaming-protocol]].

---

## Architecture

`mobile/AGENTS.md` is the standards file. It does not inherit `web/AGENTS.md`.
Read it before you write mobile code.

```
AuthGate (components/auth/AuthGate.tsx) ── resolveAuthGate ── redirect or render
  └─ (app)/_layout.tsx: ChatSurface overlay + Stack + AppSidebar
       └─ useChatController.onSubmit (hooks/useChatController.ts)
            ├─ chatSessionStore (one entry per session, never persisted)
            └─ streamChatMessage (api/chat/stream.ts, expo/fetch)
                 └─ NDJSON buffer (chat/ndjson.ts) → messageProcessor → findRenderer
```

**One chat surface.** `mobile/src/app/(app)/_layout.tsx` mounts `ChatSurface`
as an opaque overlay beside the expo-router `Stack`. Chat routes render
`null`. `chat/chatFocus.ts:deriveFocus` maps the path to the empty state, a
chat or a project. The header and composer stay mounted across these changes,
and the URL still changes for deep links and the back stack. On other routes
`deriveFocus` returns `null`, and the Stack screen shows.

**Auth, client side.** `api/auth/sessionManager.ts` owns sign-in, refresh and
sign-out. `installSession` bumps `sessionEpoch`, stores the token, purges every
cache, and then marks the session signed in. `refreshToken` shares one
in-flight refresh across callers (`api/auth/refreshState.ts`). The token lives
in `expo-secure-store`, keyed by instance URL.

**Auth, server side.** `server/auth/mobile.py` builds login, refresh and logout
from `mobile_auth_backend` (`backend/onyx/auth/users.py`). That backend uses the
same session strategy as the web cookie backend with a bearer transport, so
mobile gets the same token the web gets in a cookie. Google sign-in uses a
separate OAuth router at `/auth/mobile/oauth`, which `backend/onyx/main.py`
mounts only when `OAUTH_ENABLED`. After the IdP callback,
`auth/mobile_sso/sso_completion.py:complete_mobile_sso` stores the token behind
a one-time code (`auth/mobile_sso/code_store.py:store_sso_code`, TTL
`MOBILE_SSO_CODE_TTL_SECONDS`) and redirects to the app deep link with the code
only. The app trades the code and its PKCE verifier at
`/auth/mobile/sso/exchange`.

**Streaming.** `api/chat/stream.ts` is the one module that does not use
`apiFetch`, because only `expo/fetch` exposes a readable body on React Native.
`streamChatMessage` yields packets, the message-id object and stream errors,
told apart by field presence. It drops heartbeats. `resumeChatMessage` keeps
them as liveness ticks. Stop calls `stop-chat-session` with the response id
from the message-id packet and aborts the local `AbortController`, because a
client abort alone leaves the backend generating. Before that packet arrives,
`mobile/src/hooks/useChatController.ts:stop` waits for it (`STOP_ACK_TIMEOUT_MS`), then
aborts locally and never sends an unscoped Stop.

**Readiness.** When delivery ends, the session goes to `settling` and
`chat/sessionReadiness.ts:waitForSessionIdle` polls
`GET /chat/chat-session/{id}/status` until `is_processing` is `false`. Only
then does the chat state return to `input`. A resumed stream in
`hooks/useChatSessionController.ts` also waits for idle before it loads the
saved history.

**Timeline.** `chat/messageProcessor.ts` and `hooks/timeline/` port the packet
processor of the web app. Packets group by `getGroupKey` (`turn_index` and
`tab_index`). `injectSectionEnd` closes open groups when a new turn starts and
on `stop`, because the backend does not send `section_end` for every group,
and never for the final answer. Two hooks differ from web because the mobile
lint forbids reading refs during render: `usePacketProcessor` regroups in a
`useMemo`, and `usePacedTurnGroups` keeps pacing state in effects.

**Composer tools.** `state/ComposerToolsProvider.tsx` holds the tool state.
`resolveToolOptions` gives the controller `deep_research`, `forced_tool_id`,
`allowed_tool_ids` and the search filters at send time. Sources are tied to the
search tool: turning a source on forces search, and turning search off clears
the sources.

---

## Contracts and traps

1. `install-token-before-purge` **Install the token before the cache purge.**
   `api/auth/sessionManager.ts:installSession` calls `setToken` and then
   `purgeCache`. In the other order, a query that fires during the purge fills
   the cache again with the data of the previous user.
2. `auth-guard-epoch-and-url` **Every async auth result must check both
   `sessionEpoch` and the stored server URL.**
   `api/auth/sessionManager.ts:sameSession` does this for refresh. The epoch
   alone misses an instance switch. A late refresh would then file the bearer
   of one instance under the key of another, and every later request would
   send it to the wrong server. A new async auth flow must use the same guard.
3. `sign-out-only-on-auth-error` **Sign out only on an auth error.**
   `api/auth/sessionManager.ts:refreshToken` calls `clearLocalSession` only when `isAuthError` is true. A
   transient failure throws and keeps the token.
4. `purge-clears-every-store` **`purgeCache` must clear every client store.**
   `userFileStore` lives outside the Query cache, so
   `api/auth/sessionManager.ts:purgeCache` resets it by hand. A new store that holds user data must join `purgeCache`.
5. `mmkv-snapshot-unencrypted` **The MMKV query snapshot is unencrypted.**
   `query/client.ts:isNonPersistedKey` keeps every `chat-*` key and the keys in
   `NON_PERSISTED_KEY_PREFIXES` (identity, agents, workspace settings, projects,
   recent files) out of it. A new key with chat content, the name of a person
   or a file name must start with `chat-` or join that list.
6. `token-in-secure-store` **The token stays in `expo-secure-store`.** Do not
   put it in MMKV, Query state or a store. Read and write it only through
   `api/auth/tokenStore.ts`.
7. `no-renderer-renders-nothing` **A packet with no renderer renders
   nothing.** `components/chat/renderers/RendererComponent.tsx` falls back to
   empty content when `findRenderer` returns `null`. A new backend tool appears
   to do nothing on mobile, with no error.
8. `keep-null-tool-predicates` **Keep the `null` tool predicates in
   `components/chat/renderers/findRenderer.ts:findRenderer`.** The reasoning check is last and matches `section_end` and
   `error`. If you delete a tool predicate that returns `null`, the reasoning
   renderer claims the closed group of that tool and shows a search or image
   step as "Thinking". To add a renderer, replace one `null`.
9. `packet-enum-mirrored` **The packet enum is mirrored by hand.**
   `mobile/src/chat/streamingModels.ts` copies the backend `StreamingType`
   apart from web. [[streaming-protocol]] owns the list of mirrors that a new
   packet type must update.
10. `stream-end-is-not-idle` **The end of a stream does not enable Send.**
    The server can still save the turn after delivery ends, so only the status
    poll in `chat/sessionReadiness.ts:waitForSessionIdle` returns the session
    to `input`. A transient failure keeps polling. An auth error or a 404
    stops the poll and leaves the state `unconfirmed`. A server without the
    status route answers 404, so a new app on an older server cannot send a
    second message in a session. Keep each `stillOurs` guard in
    `hooks/useChatController.ts`: a stale callback must not release a newer
    send's controller.
11. `sso-exchange-uniform-failure` **The mobile SSO exchange fails the same way
    for every bad input.**
    `auth/mobile_sso/code_store.py:consume_sso_code` burns the code with
    `GETDEL` before it checks the PKCE verifier. A wrong, expired or replayed
    code and a bad verifier all return one 401. The deep link carries only the
    code, never the token. The app redirect URI must be in
    `MOBILE_ALLOWED_REDIRECT_URIS`.

---

## Decisions

- **The chat layer is not shared with web.** `mobile/src/chat/` duplicates
  the NDJSON parser, message tree and contracts of the web app. Sharing would
  need a shared util, a web change, a jest module mapper and coupling to a
  `dist` build. `mobile/AGENTS.md` ("Shared package") gives the full reason and
  the rule to extract again if the copies drift.
- **The bearer token is the web session token.** One session strategy serves
  both clients. Only the transport differs, so revocation works the same way.

---

## Known issues

- **Only text and reasoning render.** Every tool family falls through to
  `null` in `components/chat/renderers/findRenderer.ts`. The comments mark each
  slot as planned work.
- **The mobile enum keeps packet types that the backend never sends**
  (`MESSAGE_END`, `TOP_LEVEL_BRANCHING`), and `chat/messageProcessor.ts` still
  checks `MESSAGE_END` for `isComplete` ([[streaming-protocol]]).
- **Mobile sign-in supports only password and env-configured Google.**
  `mobile/src/api/auth/providers.ts:PROVIDER_REGISTRY` lists no OIDC or SAML
  entry.

---

## Dependencies

- [[core-chat-loop]]: the send, resume, stop and session status endpoints.
- [[streaming-protocol]]: the packet set that the mobile enum mirrors.
- [[citations]]: `chat/messageProcessor.ts` folds `CitationInfo` into the citation map that the sources sheet reads.
- [[auth-and-identity]]: the session strategy and the IdP callback that `complete_mobile_sso` extends.
- [[chat-persistence]]: chat sessions and their messages.
- [[agents-personas]]: agents and the per-agent tool preferences.
- [[projects]]: projects and project files.

---

## Recipes

- `add-tool-renderer` **Add a renderer for a tool.** Copy
  `components/chat/renderers/ReasoningRenderer.tsx`, and port the web renderer
  from `web/src/app/app/message/messageComponents/timeline/renderers/` to the
  render-prop contract in `components/chat/renderers/timelineContract.ts`.
  Return it from the matching `null` slot in
  `components/chat/renderers/findRenderer.ts`
  ([[#keep-null-tool-predicates]]). For a new packet family, also add its
  types to each hand-written set that switches on `PacketType`. To find the
  sets, run `git grep -l 'PacketType.PYTHON_TOOL_START' mobile/src` and add the
  new type where a similar type appears. If the start type is missing from
  `chat/messageProcessor.ts:CONTENT_PACKET_TYPES_SET`, the group is dropped. A
  miss renders nothing and shows no error.
- `add-query-key` **Add a query key.** Copy an existing key in `api/query-keys.ts`, and decide
  whether it may persist ([[#mmkv-snapshot-unencrypted]]).
- `run-local` **Run the app against a local backend.** Follow `mobile/GETTING_STARTED.md`.
  The app needs a development build, not Expo Go.
- `investigate-empty-step` **Investigate an answer step that shows empty.** Find the packet types of
  the step, then check `findRenderer`. An empty step with no error means no
  renderer ([[#no-renderer-renders-nothing]]), not a stream failure.

---

## Verification

- `cd mobile && bun run typecheck && bun run lint && bunx jest`. Tests live in
  `__tests__/` folders next to the code, for example
  `mobile/src/api/auth/__tests__/` for the session rules.
- By hand: send a question that runs a search. The answer and citations must
  render, and the search step must be empty, not an error. Switch the instance
  URL and confirm that no data from the first instance shows.
