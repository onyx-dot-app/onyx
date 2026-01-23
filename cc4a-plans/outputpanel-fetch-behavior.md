# OutputPanel Webapp Fetch Refactor

## Overview

Refactor `OutputPanel.tsx` webapp fetching to:
1. Defer fetch until panel animation completes
2. Unmount iframe when closed, with session-scoped URL caching
3. Refetch only on `web/` file changes (stale-while-revalidate)
4. Show CraftingLoader with smooth crossfade to iframe

## Files to Modify

| File | Changes |
|------|---------|
| `OutputPanel.tsx` | Add `isFullyOpen`, `cachedWebappUrl`, `cachedForSessionId` state; update SWR config; crossfade PreviewTab |
| `useBuildSessionStore.ts` | Add `webappNeedsRefresh` field, `triggerWebappRefresh`/`resetWebappRefresh` actions |
| `useBuildStreaming.ts` | Detect `web/` file paths in `tool_call_progress`, call `triggerWebappRefresh` |

---

## Implementation

### 1. Defer Fetch Until Panel Fully Open

Add local state to track animation completion:

```typescript
const [isFullyOpen, setIsFullyOpen] = useState(false);

useEffect(() => {
  if (isOpen) {
    const timer = setTimeout(() => setIsFullyOpen(true), 300);
    return () => clearTimeout(timer);
  } else {
    setIsFullyOpen(false);
  }
}, [isOpen]);
```

Update fetch condition:

```typescript
const shouldFetchWebapp =
  isFullyOpen &&  // NEW
  session?.id &&
  !session.id.startsWith("temp-") &&
  session.status !== "creating";
```

### 2. Session-Scoped URL Caching

Cache the webapp URL per-session to show instantly on re-open, but clear when switching sessions:

```typescript
const [cachedWebappUrl, setCachedWebappUrl] = useState<string | null>(null);
const [cachedForSessionId, setCachedForSessionId] = useState<string | null>(null);

// Clear cache on session change
useEffect(() => {
  if (session?.id !== cachedForSessionId) {
    setCachedWebappUrl(null);
    setCachedForSessionId(session?.id ?? null);
  }
}, [session?.id, cachedForSessionId]);

// Update cache when SWR returns data
useEffect(() => {
  if (webappInfo?.webapp_url && session?.id === cachedForSessionId) {
    setCachedWebappUrl(webappInfo.webapp_url);
  }
}, [webappInfo?.webapp_url, session?.id, cachedForSessionId]);

// Use cache only if it belongs to current session
const validCachedUrl = cachedForSessionId === session?.id ? cachedWebappUrl : null;
const displayUrl = webappUrl ?? validCachedUrl;
```

Conditionally render iframe only when panel is open:

```typescript
{activeTab === "preview" && isOpen && (
  <PreviewTab
    webappUrl={displayUrl}
    hasWebapp={hasWebapp || !!validCachedUrl}
    isValidating={isValidating}
  />
)}
```

### 3. Event-Based Refresh on `web/` File Changes

#### 3a. Store changes (`useBuildSessionStore.ts`)

```typescript
// Add to BuildSessionData interface
webappNeedsRefresh: boolean;

// Add actions
triggerWebappRefresh: (sessionId: string) => void;
resetWebappRefresh: (sessionId: string) => void;

// Add selector hook
export const useWebappNeedsRefresh = () =>
  useBuildSessionStore((state) =>
    state.sessions.get(state.currentSessionId ?? '')?.webappNeedsRefresh ?? false
  );
```

#### 3b. Streaming detection (`useBuildStreaming.ts`)

In `tool_call_progress` case, add:

```typescript
// Check if this is a file operation in web/ directory
const filePath = getFilePath(packetData);
const isWebFileChange =
  (kind === "edit" || kind === "write") &&
  filePath?.includes("/web/");

if (isWebFileChange && status === "completed") {
  triggerWebappRefresh(sessionId);
}
```

Helper function:

```typescript
function getFilePath(packet: Record<string, unknown>): string | null {
  const rawInput = packet.raw_input as Record<string, unknown> | null;
  return (rawInput?.file_path ?? rawInput?.filePath ?? rawInput?.path) as string | null;
}
```

#### 3c. SWR config (`OutputPanel.tsx`)

```typescript
const webappNeedsRefresh = useWebappNeedsRefresh();

const { data: webappInfo, mutate, isValidating } = useSWR(
  shouldFetchWebapp ? `/api/build/sessions/${session.id}/webapp` : null,
  () => fetchWebappInfo(session.id),
  {
    refreshInterval: 0,        // Disable polling
    revalidateOnFocus: true,
    keepPreviousData: true,    // Stale-while-revalidate
  }
);

// Refresh when web/ file changes
useEffect(() => {
  if (webappNeedsRefresh && isFullyOpen) {
    mutate();
    resetWebappRefresh(session?.id);
  }
}, [webappNeedsRefresh, isFullyOpen, mutate, session?.id]);
```

### 4. CraftingLoader with Crossfade Transition

Render both loader and iframe, crossfade based on iframe load state:

```typescript
function PreviewTab({ webappUrl, hasWebapp, isValidating }: PreviewTabProps) {
  const [iframeLoaded, setIframeLoaded] = useState(false);

  // Reset on URL change
  useEffect(() => {
    setIframeLoaded(false);
  }, [webappUrl]);

  const hasContent = hasWebapp || !!webappUrl;

  if (!hasContent) {
    return <CraftingLoader />;
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex flex-row items-center justify-between p-3 border-b border-border-01">
        {webappUrl && (
          <a href={webappUrl} target="_blank" rel="noopener noreferrer">
            <Button action tertiary rightIcon={SvgExternalLink}>Open</Button>
          </a>
        )}
        {isValidating && <span className="text-xs text-text-02">Refreshing...</span>}
      </div>

      {/* Crossfade container */}
      <div className="flex-1 p-3 relative">
        {/* Iframe - fades in when loaded */}
        {webappUrl && (
          <iframe
            src={webappUrl}
            onLoad={() => setIframeLoaded(true)}
            className={cn(
              "absolute inset-0 w-full h-full rounded-08 border border-border-01 bg-white",
              "transition-opacity duration-300",
              iframeLoaded ? "opacity-100" : "opacity-0"
            )}
            sandbox="allow-scripts allow-same-origin allow-forms"
            title="Web App Preview"
          />
        )}

        {/* Loader - fades out when iframe ready */}
        <div className={cn(
          "absolute inset-0 transition-opacity duration-300",
          iframeLoaded ? "opacity-0 pointer-events-none" : "opacity-100"
        )}>
          <CraftingLoader />
        </div>
      </div>
    </div>
  );
}
```

---

## State Flow Summary

| Scenario | Behavior |
|----------|----------|
| **First open** | Wait 300ms → fetch → CraftingLoader → crossfade to iframe |
| **Close panel** | Unmount iframe immediately, preserve `cachedWebappUrl` |
| **Re-open (same session)** | Wait 300ms → render iframe with cached URL → SWR revalidates in background |
| **Switch session** | Clear cache → CraftingLoader → fetch new session's webapp |
| **Agent edits `web/` file** | `triggerWebappRefresh` → SWR mutate with `keepPreviousData` (no loader flash) |

---

## Testing Checklist

- [ ] First open: CraftingLoader shows, crossfades to iframe when loaded
- [ ] Close: iframe unmounts (verify in DevTools)
- [ ] Re-open same session: iframe shows cached URL immediately, no loader
- [ ] Switch session: loader shows (not previous session's webapp)
- [ ] Edit `web/` file: iframe refreshes silently (no loader)
- [ ] Edit non-`web/` file: no refresh triggered
- [ ] Panel animation smooth (60fps)
- [ ] Rapid open/close: no race conditions
