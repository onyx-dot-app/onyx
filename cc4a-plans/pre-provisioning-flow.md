# Pre-Provisioning Flow

This document outlines the complete pre-provisioning flow for build sessions, including both Zustand (local) state and backend state transitions.

## Overview

Pre-provisioning creates a backend session + sandbox **before** the user sends their first message, reducing perceived latency. The session sits in a "ready" state until consumed.

---

## State Locations

### Zustand Store (Local)
```typescript
// Pre-provisioning state (discriminated union - exactly one state at a time)
type PreProvisioningState =
  | { status: "idle" }
  | { status: "provisioning"; promise: Promise<string | null> }
  | { status: "ready"; sessionId: string };

preProvisioning: PreProvisioningState     // Current pre-provisioning state

// Session data (per session)
sessions: Map<string, BuildSessionData>   // Local session data
currentSessionId: string | null           // Currently active session
```

### Backend
- **BuildSession** record in database (id, user_id, status, etc.)
- **Sandbox** provisioned and running (or ready)

---

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRE-PROVISIONING FLOW                              │
└─────────────────────────────────────────────────────────────────────────────┘

USER LANDS ON /build/v1 (no session ID in URL)
                │
                ▼
┌─────────────────────────────────────────┐
│  Session Controller Effect Runs          │
│  - Sees existingSessionId === null       │
│  - Calls ensurePreProvisionedSession()   │
└─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐     ┌─────────────────────────────┐
│  ZUSTAND STATE                          │     │  BACKEND STATE               │
│  preProvisioning: {                     │────▶│  POST /sessions              │
│    status: "provisioning",              │     │  - Creates BuildSession      │
│    promise: Promise<...>                │     │  - Provisions Sandbox        │
│  }                                      │     │                              │
└─────────────────────────────────────────┘     └─────────────────────────────┘
                │                                            │
                │                                            │
                ▼                                            ▼
┌─────────────────────────────────────────┐     ┌─────────────────────────────┐
│  API call completes                     │     │  Backend session ready       │
│  preProvisioning: {                     │     │  - Session ID exists         │
│    status: "ready",                     │     │  - Sandbox status: running   │
│    sessionId: "abc-123"                 │     │                              │
│  }                                      │     │                              │
└─────────────────────────────────────────┘     └─────────────────────────────┘
                │
                │  User is on welcome page, sandbox ready in background
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER SUBMITS MESSAGE                            │
└─────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  handleSubmit() in ChatPanel            │
│  1. consumePreProvisionedSession()      │
│     - Waits for promise if still active │
│     - Returns preProvisionedSessionId   │
│     - Clears preProvisionedSessionId    │
│     - Adds to sessionHistory            │
└─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  2. createSession(sessionId, {...})     │
│     LOCAL STATE ONLY - no API call      │
│                                         │
│     sessions.set("abc-123", {           │
│       isLoaded: true,    // prevent     │
│       messages: [user],  // overwrite   │
│       status: "running", // disable UI  │
│     })                                  │
└─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  3. Upload files (if any)               │
│     POST /sessions/{id}/files           │
└─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  4. router.push(/build/v1?session=abc)  │
│     Navigation triggers URL change      │
└─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  5. Session Controller sees URL change  │
│     - existingSessionId = "abc-123"     │
│     - Calls setCurrentSession("abc-123")│
│     - Session already exists in store   │
│       (from step 2), so NOT overwritten │
│     - currentSessionId = "abc-123"      │
└─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐     ┌─────────────────────────────┐
│  6. streamMessage(sessionId, message)   │────▶│  POST /sessions/{id}/stream │
│     - Sends user message to backend     │     │  - Executes agent loop      │
│     - Receives streaming response       │     │  - Returns SSE events       │
│     - Updates session.messages          │     │                             │
│     - Sets status: "idle" when done     │     │                             │
└─────────────────────────────────────────┘     └─────────────────────────────┘
```

---

## Detailed State Transitions

### Phase 1: User Lands on New Build Page

| Step | Trigger | Zustand State | Backend State |
|------|---------|---------------|---------------|
| 1a | URL is `/build/v1` (no session param) | `currentSessionId: null`, `preProvisioning: { status: "idle" }` | - |
| 1b | Session controller effect runs | `preProvisioning: { status: "provisioning", promise }` | API call in flight |
| 1c | API returns | `preProvisioning: { status: "ready", sessionId: "abc-123" }` | Session + sandbox exist |

### Phase 2: User Submits Message

| Step | Trigger | Zustand State | Backend State |
|------|---------|---------------|---------------|
| 2a | `consumePreProvisionedSession()` | `preProvisioning: { status: "idle" }`, `sessionHistory: [..., new entry]` | No change |
| 2b | `createSession(id, {...})` | `sessions.get("abc-123"): { isLoaded: true, status: "running", messages: [user] }` | No change |
| 2c | `router.push()` | No immediate change | No change |
| 2d | Session controller: `setCurrentSession()` | `currentSessionId: "abc-123"` | No change |
| 2e | `streamMessage()` starts | `sessions.get("abc-123").status: "running"` | Processing message |
| 2f | Stream completes | `sessions.get("abc-123").status: "idle"`, messages updated | Response complete |

---

## Key Functions

### `ensurePreProvisionedSession()` (Store Action)
- Called by session controller when on new build page
- Idempotent: returns existing promise/session if already provisioning
- Makes `POST /sessions` API call
- Sets `preProvisionedSessionId` when complete

### `consumePreProvisionedSession()` (Store Action)
- Called by ChatPanel when user submits first message
- Waits for provisioning if still in progress
- Returns session ID and clears pre-provisioning state
- Optimistically adds to session history

### `createSession(id, data)` (Store Action)
- Initializes LOCAL Zustand store entry only
- Does NOT make any API call
- Used to set initial state before navigation

### `setCurrentSession(id)` (Store Action)
- Sets which session is "current" for UI
- Creates default session data if not exists
- Called by session controller based on URL

---

## Why This Design?

### Problem: Race Condition
Previously, ChatPanel called `setCurrentSession()` directly, but the session controller also managed `currentSessionId`. This caused race conditions where the controller would reset the session to null.

### Solution: URL-Driven State
- Session controller is the **single source of truth** for `currentSessionId`
- ChatPanel navigates to URLs, doesn't set `currentSessionId` directly
- `createSession()` initializes local data BEFORE navigation
- `isLoaded: true` prevents `loadSession()` from overwriting local data

### Why `createSession()` before navigation?
1. **User message appears immediately** - we add it to local state
2. **Input is disabled** - `status: "running"` prevents double-submit
3. **Data isn't overwritten** - `isLoaded: true` tells store not to fetch from server

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| User submits before provisioning completes | `consumePreProvisionedSession()` awaits `preProvisioningPromise` |
| User refreshes page during provisioning | New provisioning starts (old one abandoned) |
| User navigates to existing session | Pre-provisioned session stays available for later |
| Pre-provisioning fails | Falls back to `createNewSession()` which creates session synchronously |
| User clicks "New Build" from existing session | Navigates to `/build/v1`, triggers new pre-provisioning |

---

## Files Involved

| File | Role |
|------|------|
| `useBuildSessionStore.ts` | Zustand store with pre-provisioning state and actions |
| `useBuildSessionController.ts` | Triggers pre-provisioning, manages currentSessionId based on URL |
| `ChatPanel.tsx` | Consumes pre-provisioned session on submit, initializes local state |
| `SandboxStatusIndicator.tsx` | Shows provisioning/ready status to user |
| `apiServices.ts` | `createSession()` API call to backend |
