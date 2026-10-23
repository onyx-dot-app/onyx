# Mobile App

> The React Native and Expo client. It is the second client of the [[core-chat-loop]]
> backend, built independently of [[chat-frontend]]: its own auth transport, its own
> hand-mirrored copy of the NDJSON parser and packet enum, and a much smaller slice of
> the packet vocabulary actually wired to a renderer.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE
**Owns:**
`mobile/src/api/` (`auth/`, `chat/`, `files/`, `client.ts`, `config.ts`), `mobile/src/app/`
(expo-router routes), `mobile/src/chat/` (parser, message tree, contracts, timeline
transforms), `mobile/src/components/` (`chat/`, `auth/`, `ui/`, `sidebar/`, `settings/`,
`form/`, `avatars/`), `mobile/src/hooks/`, `mobile/src/query/`, `mobile/src/state/`,
`mobile/src/icons/`, `mobile/src/logos/`, `backend/onyx/server/auth/mobile.py`,
`backend/onyx/auth/mobile_sso/`

**Read first:** `mobile/AGENTS.md`. It is the authoritative standards file for this
component and explicitly does **not** inherit `web/AGENTS.md`. `docs/mobile-chat/00-index.md`
through `06-unified-chat-surface.md` are design docs, not a record of current behaviour;
verify every claim against code before trusting a doc there (see §9).

---

## 1. What the user experiences

The user installs a development build (not Expo Go), connects it to an Onyx instance URL,
and signs in with email/password or a browser SSO flow. They land on a chat surface that
morphs between an empty state, an existing conversation, and a project view without a
screen transition. They can pick an agent, pick a project, type a message, attach a
document or a photo-library image, turn on deep research, force a tool, pick a model
for the turn, and watch the answer stream in with citations that
resolve to a sources sheet. They can stop generation and reopen a past session from the
sidebar.

They cannot regenerate or edit a past message, give thumbs up/down feedback, compare two
models side by side, use voice input, or watch tool activity (search, code execution,
image generation, deep research, memory) render as anything beyond a stream that
temporarily produces no visible content for that block. See §4.4 and §9.

---

## 2. Surfaces

### Routes (`mobile/src/app/`, expo-router)

| Route | File | Notes |
|---|---|---|
| `/` | `(app)/index.tsx` | Landing / empty chat state. |
| `/chat/[id]` | `(app)/chat/[id].tsx` | An existing conversation. |
| `/projects/[id]` | `(app)/projects/[id].tsx` | Project home: context panel plus the project's session list. |
| `/agents` | `(app)/agents.tsx` | Agent picker. |
| `/sources/[id]` | `(app)/sources/[id].tsx` | Source/connector detail. |
| `/(auth)/login`, `/signup`, `/connect` | `(auth)/login.tsx`, `signup.tsx`, `connect.tsx` | Instance-URL entry, then credential or SSO login. |

`(app)/_layout.tsx` mounts `ChatSurface` as an absolute-fill overlay sibling to `<Stack>`,
plus `AppSidebar`, `ComposerDraftProvider`, and `UploadReconciler`
(`mobile/src/app/(app)/_layout.tsx:AppLayout`). Chat routes render `null`; `ChatSurface`
derives a `ChatFocus` from `usePathname()` via `chatFocus.ts:deriveFocus` and renders the
matching content without remounting, so the header and composer persist across
new/chat/project transitions (`docs/mobile-chat/06-unified-chat-surface.md`). `AuthGate`
(`mobile/src/components/auth/AuthGate.tsx:AuthGate`) wraps the whole router tree and
redirects imperatively based on `resolveAuthGate` (`components/auth/authRoute.ts`).

### Backend endpoints this component calls

| Endpoint | Called from |
|---|---|
| `POST /auth/mobile/login` | `api/auth/sessionManager.ts:passwordLogin` |
| `POST /auth/mobile/refresh` | `api/auth/sessionManager.ts:refreshToken` |
| `POST /auth/mobile/logout` | `api/auth/sessionManager.ts:logout` |
| `POST /auth/mobile/sso/exchange` | `api/auth/sessionManager.ts:browserLogin` |
| `POST /auth/register` | `api/auth/sessionManager.ts:register` (shared web/mobile route; mints no token) |
| `GET /me` | `hooks/useCurrentUser.ts` |
| `POST /chat/send-chat-message` | `api/chat/stream.ts:streamChatMessage` |
| `GET /chat/chat-session/{id}/resume-stream?cursor=` | `api/chat/stream.ts:resumeChatMessage` |
| `GET /chat/get-chat-session/{id}` | `api/chat/sessions.ts` |
| `POST /chat/stop-chat-session/{id}?stream_id=` | `api/chat/sessions.ts:stopChatSession`, called from `hooks/useChatController.ts:stop`. `stream_id` is the reserved assistant message id; the app omits it before the id packet arrives, and the backend then stops the stream in flight. |
| `POST /chat/create-chat-session`, `GET /chat/get-user-chat-sessions` | `api/chat/sessions.ts` |
| `GET /auth/type` | `api/auth/useAuthConfig.ts` |
| `GET /llm/persona/{id}/providers`, `GET /tool`, `GET/PUT /user/assistant/preferences` | `api/chat/llm.ts`, `api/tools.ts`, `api/chat/agentPreferences.ts` |
| `/user/projects/file/statuses`, `/user/projects/{id}/files/{fileId}` | `api/chat/projects.ts` |
| `PUT /chat/rename-chat-session` | `api/chat/sessions.ts` |
| `GET /persona` | `api/chat/agents.ts` |
| `POST /user/pinned-assistants` | `api/chat/agents.ts` |
| `GET /user/projects`, `GET /user/projects/{id}/details` | `api/chat/projects.ts` |
| `GET /manage/connector-status`, `GET /federated` | `api/chat/connectors.ts` |
| `GET /settings` | `api/settings.ts` |

The mobile-specific endpoints (`/auth/mobile/*`) are owned by
`backend/onyx/server/auth/mobile.py`; every other endpoint above is owned by
[[core-chat-loop]], [[chat-persistence]], [[agents-personas]], [[projects]], or
[[onyx-api]]'s connector-status surface and is unchanged from what [[chat-frontend]]
calls, modulo the mobile app calling a **subset** (no multi-model, no feedback, no
message-branch endpoints).

### Environment / build configuration

`mobile/app.json`, `mobile/metro.config.js`, `mobile/tailwind.config.js` (NativeWind
content globs), `mobile/patches/` (dependency patches applied via a postinstall patch
step). `api/config.ts:getBaseUrl()` resolves the active instance URL and appends the
`/api` prefix; every `apiFetch` call path is bare (`"/chat/..."`, `"/me"`).

---

## 3. Data model

No new backend tables. Client-side state only.

- **Tokens**: `mobile/src/api/auth/tokenStore.ts`. A single bearer access token per
  instance, stored in `expo-secure-store` (iOS Keychain / Android Keystore) under a key
  derived from the current base URL (`tokenStore.ts:getAccessTokenKey`), with
  `keychainAccessible: WHEN_UNLOCKED_THIS_DEVICE_ONLY` so it never syncs to iCloud/backup
  and never crosses instances. This is the credential of record; see §5 for why it must
  stay out of MMKV.
- **Server-state cache**: TanStack Query, persisted to MMKV via
  `query/client.ts:persister` (`createSyncStoragePersister`), keyed so a
  `serverUrl`-scoped query key never serves another instance's data
  (`api/query-keys.ts`, per `mobile/AGENTS.md`). `dehydrateOptions.shouldDehydrateQuery`
  (`query/client.ts`) excludes any key whose head matches `me`, `agents`,
  `workspaceSettings`, `userProjects`, `userProject`, `userRecentFiles`, or that starts
  with `"chat-"`, from the on-disk MMKV snapshot; those stay in-memory only, because MMKV
  here is unencrypted (`query/client.ts`, the `NON_PERSISTED_KEY_PREFIXES` comment). A
  new query key with chat content or identity in it must be added to this exclusion or
  land under a `chat-` prefix.
- **Per-session chat state**: `mobile/src/state/chatSessionStore.ts` (`useChatSessionStore`,
  a Zustand store), a `Map<string, SessionData>` keyed by session id, holding
  `messageTree`, `chatState`, `abortController`, `submittedMessage`. Never persisted; it
  holds a live `AbortController` (`chatSessionStore.ts`, header comment).
- **Message tree**: `mobile/src/chat/messageTree.ts`, the same `nodeId`-keyed tree shape
  as web (`MessageTreeState`), built by `mobile/src/chat/chatHistory.ts` from
  `GET /chat/get-chat-session/{id}`.
- **Processed message state**: `mobile/src/chat/messageProcessor.ts` folds a message's
  packets into `citationMap`, `citations` (`StreamingCitation[]`), and a document map, the
  same fold pattern as web's `getCitations` (`messageProcessor.ts`, `citation_info`
  handling).
- **User files**: `mobile/src/state/userFileStore.ts`, separate from the Query cache so
  `sessionManager.ts:purgeCache` must clear both on login/logout.

---

## 4. How it works

### 4.1 App start and auth

```
AuthGate                                  components/auth/AuthGate.tsx
  ├─ useCurrentUser (GET /me)             hooks/useCurrentUser.ts
  ├─ useTokenRefresh(identity confirmed)  hooks/useTokenRefresh.ts
  └─ resolveAuthGate                      components/auth/authRoute.ts  → redirect / render
```

`useTokenRefresh` is gated on `data !== undefined` (identity confirmed) so a refresh
cannot race the persisted-cache restore (`useTokenRefresh.ts` doc comment). It fires once
immediately, then on every foreground transition (`AppState` `"active"`, min gap 60 s) and
on a 10-minute interval while foregrounded; iOS suspends JS timers in the background, so
the foreground listener is the real trigger, not the interval (`useTokenRefresh.ts`).

Login (`api/auth/sessionManager.ts:login`) resolves an access token via one of two paths
and calls `installSession`:
- **Password**: `passwordLogin` posts an OAuth2 password form (`username`/`password`, not
  JSON) to `/auth/mobile/login`.
- **Browser SSO**: `browserLogin` runs `runBrowserSso` (`api/auth/browserSso.ts`), which
  opens the system browser for the provider's OAuth flow and gets back a one-time
  `code` + the `codeVerifier` it generated, then exchanges them at
  `/auth/mobile/sso/exchange`.

`installSession` bumps `sessionEpoch`, writes the token via `setToken`, then
`purgeCache()` (clears the Query client, the user-file store, toasts, and the MMKV
persister) before flipping `useSession` status to `"authed"`
(`sessionManager.ts:installSession`). Token-before-purge ordering matters: a query firing
mid-purge must not repopulate the cache with the previous user's data.

`refreshToken` de-dupes concurrent callers through `refreshState.ts:getInFlightRefresh`/
`setInFlightRefresh`, and only clears the local session on an **auth** error
(`isAuthError`); a transient failure re-throws and leaves the existing token in place
(`sessionManager.ts:refreshToken`). `sameSession` guards against a slow refresh applying
its result after the user switched instances or logged out mid-flight, by checking both
the session epoch and the currently stored server URL (`sessionManager.ts:sameSession`).

### 4.2 The mobile auth gateway (backend)

`backend/onyx/server/auth/mobile.py` mounts the mobile bearer routes under
`/auth/mobile` in `main.py`. `login`/`refresh`/`logout` are built from
`fastapi_users.get_auth_router(mobile_auth_backend)` /
`get_refresh_router(mobile_auth_backend)`
(`mobile.py`), where `mobile_auth_backend` (`onyx/auth/users.py`) is the **same**
session-strategy backend web's cookie flow uses, differing only in transport: web gets
an HttpOnly cookie, mobile gets the identical token as a `Bearer` header value
(`mobile.py`, module docstring). It is server-revocable under the redis/postgres
strategies, and a self-contained non-revocable JWT under `AUTH_BACKEND=jwt`
(`onyx/auth/mobile_sso/tokens.py:issue_session_credential`).

SSO: `backend/onyx/auth/mobile_sso/sso_completion.py:complete_mobile_sso` runs after the
existing IdP callback (Google today, through the dedicated `/auth/mobile/oauth` router mounted in `main.py`) when the OAuth state carries a mobile marker
(`apply_mobile_state`). It mints the session token, stores it behind a single-use,
PKCE-bound code in Redis (`code_store.py:store_sso_code`, TTL
`MOBILE_SSO_CODE_TTL_SECONDS`, default 60 s), and 302-redirects to the app's custom-scheme
deep link carrying **only the opaque code**, never the token
(`sso_completion.py`). The app's `POST /auth/mobile/sso/exchange`
(`mobile.py:sso_exchange`) then calls `consume_sso_code`, which atomically `GETDEL`s the
code and constant-time-compares the PKCE verifier (S256) before returning the token
(`code_store.py:consume_sso_code`). A wrong code, an expired code, a replayed code, and a
verifier mismatch all fail identically with one 401 and no oracle
(`sso_completion.py`, `mobile.py:sso_exchange`).

### 4.3 A chat turn, send to render

```
InputBar / ActionsMenu                    components/chat/InputBar.tsx
  └─ useChatController.onSubmit           hooks/useChatController.ts
      ├─ ensureSession / optimistic node  state/chatSessionStore.ts, chat/messageTree.ts
      ├─ streamChatMessage (async gen)    api/chat/stream.ts
      │   └─ readNdjson                   api/chat/stream.ts  (expo/fetch reader)
      │       └─ NdjsonBuffer.pushChunk   chat/ndjson.ts
      └─ drain loop → messageProcessor    chat/messageProcessor.ts → chatSessionStore
```

`streamChatMessage` (`api/chat/stream.ts`) is the **one place mobile bypasses `apiFetch`**:
only `expo/fetch`'s response exposes a readable `body` on React Native
(`stream.ts`, header comment). It POSTs `SendMessageBody` to `/chat/send-chat-message` and
yields `StreamEvent`s, a union of `Packet | MessageResponseIDInfo | StreamingError`
discriminated by field presence (`isPacket`/`isMessageIdInfo`/`isStreamError`,
`stream.ts`), because the wire mixes wrapped `{placement, obj}` packets with root control
objects. `readNdjson` drops `chat_heartbeat` events unless `keepHeartbeats` is set
(`isHeartbeat`, `stream.ts`); `resumeChatMessage` keeps them, mirroring web's
`resumeStream` not filtering heartbeats (see [[streaming-protocol]] §4.4).

Stop (`hooks/useChatController.ts:stop`) calls `POST /chat/stop-chat-session/{id}`
(`api/chat/sessions.ts:stopChatSession`) and aborts the session's local
`AbortController`, the same two-part contract as web (see [[core-chat-loop]] §4.6).

### 4.4 Parsing and rendering the stream

`chat/streamingModels.ts` declares `PacketType`, one interface per packet body, and the
`ObjTypes` union, hand-mirroring the backend's `StreamingType`
(`backend/onyx/server/query_and_chat/streaming_models.py:StreamingType`), independently
of `web/src/app/app/services/streamingModels.ts` doing the same. `chat/ndjson.ts`'s
`createNdjsonBuffer` is a pure line-buffer with the identical brace-recovery fallback as
web's `handleSSEStream`, explicitly commented as matching it (`ndjson.ts`).

Packets are grouped and handed to `findRenderer`
(`mobile/src/components/chat/renderers/findRenderer.ts:findRenderer`), which checks
predicates in a fixed order and returns the first match:

| Predicate | Renderer wired? |
|---|---|
| chat packets (`message_start`/`_delta`/`_end`) | **`MessageTextRenderer`** |
| deep-research plan packets | `null` (unwired) |
| research-agent packets | `null` (unwired) |
| coding-agent packets | `null` (unwired) |
| search-tool packets | `null` (unwired) |
| image-generation packets | `null` (unwired) |
| python-tool packets | `null` (unwired) |
| file-reader packets | `null` (unwired) |
| custom-tool packets | `null` (unwired) |
| fetch (`open_url_*`) packets | `null` (unwired) |
| memory-tool packets | `null` (unwired) |
| reasoning packets, or a bare `section_end`/`error` | **`ReasoningRenderer`** |

`RendererComponent` (`mobile/src/components/chat/renderers/RendererComponent.tsx`) falls
back to `{ icon: null, status: null, content: <></> }` when `findRenderer` returns `null`
(`RendererComponent.tsx:RendererComponentImpl`), so every tool family above renders as an
empty timeline step today: not an error, not a placeholder, nothing. The file's own
comments name this as intentional interim state, tracked as future "PR 9x" work
(`findRenderer.ts`, per-branch comments), not a bug.

Citations are **not** rendered as a timeline block on mobile either, matching web:
`chat/messageProcessor.ts` folds every `CitationInfo` packet into `citationMap` and
`citations` as it streams (`messageProcessor.ts`, the `citation_info` case), and
`chat/citations.ts:selectSources` derives the cited/more/files split the `CitedSources`
sheet component renders (`components/chat/CitedSources.tsx`).

### 4.5 Session and message lifecycle

`chat/chatHistory.ts` builds the message tree from `GET /chat/get-chat-session/{id}`
(`api/chat/sessions.ts`). Renaming (`PUT /chat/rename-chat-session`) and stopping are the
only session-mutation endpoints called; there is no create/delete/share call site
distinct from `createChatSession` used implicitly by the first send. Branch switching,
message editing, regeneration, and feedback have no mobile call sites at all (see §5, §9).

---

## 5. Contracts and invariants

### Component rules (`mobile/AGENTS.md`, verified against source)

`mobile/AGENTS.md` states it "complements but does not inherit" `web/AGENTS.md`: no DOM,
NativeWind instead of web Tailwind, expo-router instead of Next.js routes. The concrete
rules:

1. **Reuse before building.** Check `components/ui/*`, the shell layouts
   (`components/{settings,sidebar,auth,chat}`), `@/icons/*` first. If only web has the
   component, port it deliberately (pixel/behaviour-exact) rather than hand-rolling a
   divergent lookalike; ask before porting.
2. **Spacing classes are literal pixels, not Tailwind's step scale.** `p-24` = 24px on
   mobile; the equivalent web class is `p-6` (step 6 = 1.5rem = 24px). Translate a web
   step `N` to mobile `N × 4`; never copy a web class number as-is
   (`mobile/AGENTS.md`, the spacing table).
3. **All text through `@/components/ui/text` `Text`.** Never React Native's own `Text`,
   including in tests.
4. **Icons through `@/icons/*` rendered via `@/components/ui/icon` `Icon`.**
5. **Colors are semantic classes** (`bg-background-*`, `text-text-*`, `border-border-*`),
   resolved at runtime by a `vars()` provider from `@onyx-ai/shared/native`. No `dark:`
   modifier, no raw Tailwind colors.
6. **HTTP goes through `@/api/client` `apiFetch<T>`**, which injects the bearer and
   normalizes errors to `ApiError`; `getBaseUrl()` already appends `/api`, so call sites
   pass bare paths. The chat stream is the one documented exception (`expo/fetch`, for a
   readable body).
7. **Server state is TanStack Query, keyed by `serverUrl`.** The MMKV-persisted cache is
   **unencrypted**; any key naming PII (chat content, identity, agent/project names, file
   names) must be excluded via `NON_PERSISTED_KEY_PREFIXES` in `query/client.ts`.
8. **Navigation is expo-router; route groups are path-transparent.** Auth routing is
   imperative (`components/auth/AuthGate.tsx`), with pure logic isolated in
   `authRoute.ts`.
9. **Tests run under `jest-expo`**, import jest globals from `@jest/globals`, and must
   not import reanimated-pulling barrels (e.g. `@/components/sidebar` as a whole) in a
   unit test; import the leaf component instead.
10. **The chat pure layer is intentionally not shared with web.** `mobile/src/chat/*`
    duplicates web's NDJSON parser, message tree, and packet contracts on purpose
    (`docs/mobile-chat/05-pr-roadmap.md`, PR 2 decision, restated in
    `mobile/AGENTS.md`). This is a deliberate acceptance of drift risk, not an oversight.

### This component's own invariants

11. **The bearer token lives only in `expo-secure-store`, never MMKV or plain state.**
    `tokenStore.ts` is the sole read/write path; a new auth-adjacent feature that needs
    the token must go through `getToken`/`setToken`, not thread it through Query state.
12. **A mobile-mirrored `PacketType` value must match the string the backend's
    `StreamingType` emits.** See [[streaming-protocol]] §5.1; this is the same contract
    web carries, verified independently here (see §7 for the drift found in this audit).
13. **A packet with no matching predicate in `findRenderer` renders nothing, not an
    error.** `RendererComponent`'s fallback (§4.4) is deliberate degrade-not-crash
    behaviour; do not let a new packet family reach an unguarded cast that assumes a
    renderer exists.
14. **`sessionEpoch` and the stored server URL together gate every async auth
    continuation** (`sameSession`, `sessionManager.ts`). A new async auth flow (a second
    SSO provider, a background token exchange) must check both before applying its
    result, or a slow response can resurrect a logged-out session or write a token under
    the wrong instance's key.

---

## 6. Relationships

**Depends on**
- [[core-chat-loop]]: the turn endpoint this component drives, identically to web modulo
  the endpoints it does not call (§2, §4.5).
- [[streaming-protocol]]: the packet vocabulary `mobile/src/chat/streamingModels.ts` and
  `ndjson.ts` mirror; that document already names this component as the second mirror.
- [[citations]]: the citation numbering `messageProcessor.ts` folds and `CitedSources.tsx`
  renders.
- [[auth-and-identity]]: this component's bearer-token session is the mobile-specific path
  through that system; web's cookie session is the other.
- [[agents-personas]]: agent selection (`api/chat/agents.ts`, `/agents` route).
- [[chat-persistence]]: `get-chat-session`, `rename-chat-session`, `stop-chat-session`.
- [[onyx-api]]: `/manage/connector-status`, `/federated` for source display.

**Depended on by**
- Nothing in-repo depends on this component; it is a leaf client, like [[chat-frontend]].

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds, renames, or removes a backend packet type (`StreamingType`) | `mobile/src/chat/streamingModels.ts:PacketType` and its interface; `mobile/src/components/chat/renderers/findRenderer.ts` needs a predicate or the packet silently renders nothing; do this alongside the same update to `web/src/app/app/services/streamingModels.ts` (see [[streaming-protocol]] §7) |
| changes mobile auth (`backend/onyx/server/auth/mobile.py`, `onyx/auth/mobile_sso/`) | `mobile/src/api/auth/*`; confirm `sessionManager.ts` still gets the same `{access_token, token_type}` shape; confirm `sameSession` guards still hold if the token-issuance seam (`tokens.py:issue_session_credential`) changes what it mints |
| changes an endpoint mobile calls (`/persona`, `/user/projects`, `/chat/get-chat-session/{id}`, ...) | the corresponding file under `mobile/src/api/chat/`; mobile calls a strict subset of what [[chat-frontend]] calls, so verify mobile's caller still matches the response shape, it will not be caught by a web-only test |
| changes the design system / design tokens | `mobile/AGENTS.md`'s spacing-conversion table stays correct only if the px-per-token relationship in `style-dictionary.config.mjs` is unchanged; a token rename needs the mobile NativeWind theme (`@onyx-ai/shared/nativewind-theme`) regenerated too |
| changes `resume_chat_stream` or the stream buffer | `api/chat/stream.ts:resumeChatMessage`; mobile keeps heartbeats on resume the same way web does, so a framing change reaches both |
| adds a message action (regenerate, edit, feedback, branch) on web | mobile has none of these wired (§4.5, §9); decide explicitly whether to port before assuming parity |

---

## 8. How to verify a change

### Running the app

`mobile/GETTING_STARTED.md` covers one-time machine setup (Xcode 26.4+, an iOS
simulator, CocoaPods; JDK 17 plus the pinned NDK version for Android).
`mobile/README.md`'s steps: `bun install` then `bunx expo install --fix` from `mobile/`,
then `bun run prebuild -- -p ios` and `bun run run:ios` (Metro on port 8082; first iOS
build compiles React Native from source, roughly 15 minutes). It is a development build,
not Expo Go: `react-native-mmkv` v4 and FlashList are native modules Expo Go lacks.

### Tests

```bash
cd mobile
bun run typecheck
bun run lint
bunx jest
```

Tests live under `src/**/__tests__/**/*.test.ts(x)`, run with `jest-expo`. Representative
real paths in this codebase: `mobile/src/chat/__tests__/ndjson.test.ts`,
`mobile/src/chat/__tests__/messageProcessor.test.ts`,
`mobile/src/chat/__tests__/citations.test.ts` (via `mobile/src/chat/__tests__/`),
`mobile/src/components/chat/renderers/__tests__/findRenderer.test.ts`,
`mobile/src/api/auth/__tests__/sessionManager.test.ts`,
`mobile/src/api/auth/__tests__/tokenStore.test.ts`,
`mobile/src/hooks/__tests__/useTokenRefresh.test.tsx`,
`mobile/src/hooks/__tests__/useChatController.test.tsx`. Native mocks (MMKV self-mock,
`expo-secure-store`) live in `mobile/src/state/__mocks__/` and per-directory `__mocks__/`
folders, wired in `jest.setup.ts`.

### Manual reproduction

1. Confirm the backend is up (`backend/log/api_server_debug.log`).
2. Launch the app against a local instance, sign in with
   `admin_user@example.com` / `TestPassword123!`.
3. Send a message that triggers a search. Confirm the answer text streams and citations
   resolve in the sources sheet; confirm the search step itself renders as an empty
   timeline block, not an error (expected current behaviour, §4.4).
4. Background the app for over a minute, foreground it, and confirm a token refresh
   attempt fires (log or network inspection) without forcing a re-login.
5. Kill and relaunch the app; confirm the cached session list still shows without
   chat content, since chat content is excluded from the MMKV snapshot.

### What "working" looks like

- No unrendered tool step is mistaken for a hang; only text and reasoning blocks are
  expected to show content today.
- A token refresh failure logs out only on an actual auth error, never on a network blip.
- Switching the instance URL never serves a previous instance's cached queries or token.

---

## 9. Footguns

- **Web habits are wrong here by design.** `mobile/AGENTS.md` is explicit that it does
  not inherit `web/AGENTS.md`: no `useSWR` (TanStack Query instead), no Opal components,
  no web Tailwind step scale, no DOM. An agent that ports a web fix by copying its class
  names or import paths will produce a broken or visually wrong screen (see rule 2, the
  spacing table).
- **The packet enum is hand-mirrored twice over, not once.** Web mirrors the backend
  `StreamingType`; mobile mirrors it independently, by an explicit repo decision not to
  share chat code with web (`docs/mobile-chat/05-pr-roadmap.md`, the 2026-06-29 override).
  A new backend packet type needs three edits, not two, to stay visible everywhere:
  `streaming_models.py`, `web/src/app/app/services/streamingModels.ts`, and
  `mobile/src/chat/streamingModels.ts`.
- **Comparing the mobile enum to the backend `StreamingType` in this audit found:**
  mobile (and web) both declare a `message_end`/`MESSAGE_END` packet type that the backend
  does not currently emit at all (no `MessageEnd`/`"message_end"` anywhere in
  `streaming_models.py`); the answer stream instead closes via `OverallStop`/`stop`, per
  [[streaming-protocol]] §5.8. This is vestigial in both clients, not a mobile-specific
  gap. Mobile also still declares `top_level_branching`, which the backend stopped
  sending (#15099) and web no longer declares. Backend's `IMAGE_GENERATION_HEARTBEAT` ("image_generation_heartbeat") has no
  matching type in **either** client's enum; it degrades harmlessly since image-generation
  packets are entirely unwired on mobile and web filters only `chat_heartbeat`, not this
  one. `TOOL_CALL_DEBUG` is absent from both clients too (it is `INTEGRATION_TESTS_MODE`-
  only). None of these three is a mobile-only drift from web; the real gap is not in the
  **enum**, it is in **renderer wiring** (next point).
- **Mobile parses the full packet vocabulary but renders almost none of it.**
  `findRenderer.ts` only wires `message_*` and reasoning/`section_end`/`error`. Search,
  image generation, python, fetch, custom tools, file reader, memory, deep research,
  coding agent, and bash tool packets all hit the `null` fallback and render as an empty
  timeline step (§4.4). This is documented in the file's own comments as staged future
  work ("PR 9x"), not a bug, but it means a PR that adds a new tool call path on the
  backend will appear to do nothing visible on mobile until its renderer lands, with no
  error to signal the gap.
- **`docs/mobile-chat/` is a plan, and parts of it are stale relative to code.** The
  index (`00-index.md`) lists citations, the agentic timeline, regenerate/edit/feedback,
  and image-gen as deferred to "PR 9". In the code as it stands, citation folding and the
  `CitedSources` sheet **have** shipped (`chat/citations.ts`, `chat/messageProcessor.ts`,
  `components/chat/CitedSources.tsx`, with tests), ahead of what the index still marks as
  deferred; regenerate/edit/feedback/multi-model and every non-text/reasoning timeline
  renderer have **not** shipped, matching the index. The unified chat surface
  (`06-unified-chat-surface.md`) has shipped in code (`ChatSurface.tsx`, `chatFocus.ts`)
  but its own header still marks on-device visual verification as pending. Always check
  the file, not the doc.
- **No message-editing, regeneration, feedback, or multi-model comparison exists on
  mobile.** `useChatController.ts` has no call sites for any of these; do not assume
  parity with [[chat-frontend]]'s message actions (§4.7 of that document) when reviewing
  a mobile PR that touches message state.
- **Only photo-library image attachment is supported, no camera capture**, per
  `docs/mobile-chat/00-index.md`'s locked scope and `api/files/pickers.ts`'s
  `ImagePicker.launchImageLibraryAsync` usage; verify a "camera" feature request isn't
  assumed to already work.
- **The credential threat model differs from web's cookie session on purpose.** A bearer
  token in `expo-secure-store` cannot be marked HttpOnly or SameSite; it is protected by
  OS keychain access control and `WHEN_UNLOCKED_THIS_DEVICE_ONLY` instead. Code that
  treats the mobile token like a web cookie (assuming automatic browser transport, or
  storing it anywhere but `tokenStore.ts`) reintroduces the exposure the keychain choice
  was meant to prevent.
