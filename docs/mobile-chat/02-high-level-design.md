> Status: active · Task: mobile-chat · Approach: C — Hybrid Seams

# Mobile Chat Port — High-Level Design

## What it does

Brings the Onyx chat experience to the native mobile app: a user opens the app, picks an agent (or uses the default), and has a streaming conversation grounded in the company's knowledge — optionally inside a project, optionally with documents/photos attached to a message. It mirrors the web product's behavior and talks to the **same backend, unchanged**; only the client is new.

## How it works (end-to-end walkthrough)

The mobile app already boots through `AuthGate` into an authenticated shell with a working sidebar and an `apiFetch` HTTP layer that injects the user's bearer token and resolves the server URL. We add an authed **chat route group** beside the existing `(auth)` group.

When the user sends a message, a **mobile orchestration hook** does three things: (1) if there's no chat session yet, it creates one on the backend (`POST /api/chat/create-chat-session`) carrying the selected agent's `persona_id` and the active `project_id`; (2) it optimistically drops a user bubble and an empty assistant bubble into an in-memory **message tree**; (3) it opens the streaming request.

The stream is the heart of it. We POST the message to `/api/chat/send-chat-message` using **`expo/fetch`** (the only HTTP call in the app that doesn't go through `apiFetch`, because it needs a readable byte stream). The backend replies with **newline-delimited JSON** — one packet per line. A **mobile-native pure parser** (mirroring the web app's line-buffering logic) turns the byte chunks into typed packet objects. The mobile hook reads those packets, ignores heartbeats, and — for the core experience — only cares about the message text packets (`MESSAGE_START/DELTA/END`) plus `STOP`/`ERROR`. It appends streamed text onto the assistant bubble, flushing updates to the UI in ~50ms batches so the screen doesn't thrash.

The chat screen renders the message tree with **FlashList v2** (non-inverted, auto-pinned to the bottom while streaming). The streaming assistant bubble renders its accumulating text through a **React Native markdown component**. When the `STOP` packet arrives, the conversation returns to idle and the assistant bubble gets its real server message-id.

Reopening a past chat fetches its history from the backend and rebuilds the message tree with a **mobile-native `processRawChatHistory`** (mirroring web's logic). Listing chats, agents, and projects all go through **TanStack Query** (already wired and persisted to MMKV), keyed by server URL so switching backends never serves stale data.

Agents, projects, and attachments layer on top of this core without changing it: agent selection just sets the `persona_id` used at session-create time; projects set the `project_id`; attachments upload files (via `expo-file-system`'s streaming upload task) and attach their `file_descriptors[]` to the send request, gating the send button until the files finish indexing.

## Component interaction

```
                    ┌─────────────────────────────────────────────┐
                    │  mobile/src/app/(app)/  (expo-router group)   │
                    │  new-chat · chat/[id] · history · projects    │
                    └───────────────┬───────────────────────────────┘
                                    │ renders
                    ┌───────────────▼───────────────┐     ┌──────────────────────┐
                    │  RN UI (mobile-only)           │     │  TanStack Query        │
                    │  MessageList (FlashList v2)    │◄────┤  sessions · agents ·   │
                    │  StreamingMarkdown · InputBar  │     │  projects · files      │
                    └───────────────┬───────────────┘     │  (apiFetch + MMKV)     │
                          subscribes│                      └──────────┬─────────────┘
                    ┌───────────────▼───────────────┐                 │ apiFetch (JSON)
                    │  chatSessionStore (zustand)    │                 ▼
                    │  per-session messageTree,      │          ┌─────────────┐
                    │  chatState, AbortController    │          │  Onyx       │
                    └───────────────┬───────────────┘          │  backend    │
                       drives ▲     │ updates                   │ (unchanged) │
                    ┌──────────┴─────▼───────────────┐          └──────▲──────┘
                    │  useChatController (mobile)     │                 │ expo/fetch
                    │  onSubmit · drain stream · flush│─────────────────┘ (NDJSON stream)
                    └───────────────┬─────────────────┘
                                    │ calls
              ┌─────────────────────▼──────────────────────┐
              │  mobile/src/chat/  (pure TS, mobile-native) │
              │  ndjson parser · contracts (chat/streaming/ │
              │  files/agents/proj) · messageTree ·         │
              │  processRawChatHistory · fileDescriptors    │
              └─────────────────────────────────────────────┘
                  (web keeps its own copies — nothing shared)
```

## Key components

- **`(app)` route group** — authed chat screens (new-chat, `chat/[id]`, history, projects). (new, mobile)
- **`useChatController` / `useChatSessionController`** — mobile orchestration: submit, drive the stream, batch flushes, stop, load/resume history. (new, mobile)
- **`chatSessionStore` (zustand)** — ephemeral per-session state: message tree, chat state, abort controller. **Not persisted.** (new, mobile)
- **expo/fetch stream wrapper** — the one streaming HTTP call; feeds bytes into the mobile-native parser. (new, mobile)
- **TanStack Query hooks** — sessions, agents, projects, files lists (persisted, keyed by server URL). (new, mobile)
- **RN UI** — `MessageList` (FlashList v2), `StreamingMarkdown`, `InputBar` (keyboard-sticky), agent picker, project screens, attachment chips. (new, mobile)
- **Mobile-native chat data layer** (`mobile/src/chat/`) — NDJSON parser + packet/chat/file **types** + message-tree math + history rebuild + file-descriptor helper; ported from web, **nothing shared** (web keeps its own copies). (new, mobile)

## End-to-end scenario

1. User opens the app → `AuthGate` lands them in the `(app)` chat home; sidebar shows their recent chats (TanStack Query over the sessions list).
2. User taps an agent in a picker → selection stored; starter prompts shown on the empty chat screen.
3. User types "Summarize the Q3 board deck" and taps send.
4. `useChatController` creates a session (`persona_id` = chosen agent) → gets `chat_session_id`, navigates to `chat/[id]`.
5. It drops a user bubble + empty assistant bubble into the message tree (`chatState='loading'`).
6. It POSTs the message via `expo/fetch`; the backend streams NDJSON packets.
7. The mobile-native parser yields packets; the hook appends `MESSAGE_DELTA` text to the assistant bubble, flushing every ~50ms (`chatState='streaming'`).
8. FlashList keeps the view pinned to the bottom; the assistant bubble renders markdown as it grows.
9. `STOP` arrives → `chatState='input'`, assistant bubble gets its server message-id, sessions list refetches so history reflects the new turn.
10. User backgrounds the app mid-answer and returns → reopening the session replays buffered packets and re-attaches to the live run.

## Sequence of key operations

1. Resolve auth + server URL (existing `AuthGate` / `sessionManager`).
2. Create chat session if none (`persona_id`, `project_id`) → `chat_session_id`.
3. Optimistically seed the message tree (user + empty assistant nodes).
4. Open `expo/fetch` POST stream with bearer + JSON body.
5. Decode bytes → mobile-native NDJSON parser → typed packets; drop heartbeats.
6. Reduce `MESSAGE_*` packets into the assistant node; batch-flush to zustand (~50ms).
7. On `STOP`/`ERROR`/abort: settle chat state, release the reader, capture message-id, refetch sessions.
8. Reopen/resume: fetch history → mobile-native `processRawChatHistory` → tree; if a run is live, tail `resume-stream`.

## Key decisions & why

- **`expo/fetch` for streaming, `apiFetch` for everything else** — RN's legacy fetch has no readable body; `expo/fetch` (SDK 56 default) exposes `response.body.getReader()`, letting us reuse the web's exact NDJSON parsing. JSON list calls stay on the existing `apiFetch` choke-point (bearer + error normalization).
- **Keep the whole chat pure layer mobile-native; share nothing** — the parser, message tree, history rebuild, and packet→display mapping are all written in `mobile/src/chat/`, with web keeping its own copies. The shared-package machinery (a `@onyx-ai/shared` util + a web re-point + jest/dist coupling) is more moving parts than the ~200 lines of duplication it removes; pre-production the backend protocol is stable, so drift is low and cheap to re-extract later if it bites. Web stays untouched. (Approach C dropped to "no shared chat code" per the **PR 2 Decision (2026-06-26)**.)
- **Two-tier state: TanStack Query for lists, zustand for the live stream** — lists benefit from the existing MMKV persistence + refetch; the streaming tree holds an `AbortController` and must *not* be persisted, so it lives in a separate, ephemeral zustand store.
- **FlashList v2 non-inverted with `maintainVisibleContentPosition`** — the modern v2 pattern for chat; pins to the bottom while streaming without yanking a user who scrolled up.

## What existing behavior changes

- **Mobile**: net-new feature; nothing pre-existing is removed.
- **Web**: behavior unchanged **and untouched** — the mobile chat port shares no code with web, so no web files are modified or re-pointed.
- **Backend**: no changes.
