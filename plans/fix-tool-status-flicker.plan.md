# Fix Tool Status Flickering When Stopped

## Problem

When a user stops a tool call partway through, the tool status text still flickers through the completion states (e.g., "Searching the web" → "Searched the web") even though the tool was interrupted. This creates a confusing UX where it appears the tool completed successfully when it was actually stopped.

## Root Cause

Individual tool renderers (`SearchToolRenderer.tsx`, `FetchToolRenderer.tsx`, `SearchToolRendererV2.tsx`) implement their own state machines with minimum display durations for various states:
- "Searching" → "Searched" (with 1 second minimum for each state)
- "Reading" → "Read" (with 1 second minimum for each state)

These renderers receive the `stopPacketSeen` prop but don't use it in their completion logic. When `stopPacketSeen` is true (indicating the stream was stopped), the renderers still:
1. Detect `isComplete` is true (because `AIMessage.tsx` injected a `SECTION_END` packet)
2. Go through the normal state transition sequence
3. Show intermediate states like "Searched" even though the tool was stopped

## Expected Behavior

When a tool is stopped:
- Skip the intermediate "completed" state (e.g., "Searched", "Read")
- Go directly from the running state to completion without flickering
- Avoid showing success states for interrupted operations

## Solution

Modify tool renderers to check `stopPacketSeen` in their completion logic:
1. If `stopPacketSeen` is true AND tool has `SECTION_END` → skip intermediate states, call `onComplete()` immediately
2. If `stopPacketSeen` is false AND tool has `SECTION_END` → use normal state transitions

## Files to Modify

1. **`web/src/app/chat/message/messageComponents/renderers/SearchToolRenderer.tsx`**
   - In the completion `useEffect` (around line 117), check `stopPacketSeen`
   - If stopped, skip the "Searched" state and call `onComplete()` immediately
   - Clear any pending timeouts to prevent flickering

2. **`web/src/app/chat/message/messageComponents/renderers/SearchToolRendererV2.tsx`**
   - Similar logic as SearchToolRenderer
   - Check `stopPacketSeen` in completion handling

3. **`web/src/app/chat/message/messageComponents/renderers/FetchToolRenderer.tsx`**
   - Check `stopPacketSeen` in the reading completion logic
   - Skip "Read" state when stopped

4. **`web/src/app/chat/message/messageComponents/renderers/CustomToolRenderer.tsx`**
   - Check if this renderer has similar issues
   - May need similar fix

5. **`web/src/app/chat/message/messageComponents/renderers/PythonToolRenderer.tsx`**
   - Check if this renderer has similar issues
   - May need similar fix

6. **`web/src/app/chat/message/messageComponents/renderers/ImageToolRenderer.tsx`**
   - Check if this renderer has similar issues
   - May need similar fix

## Implementation Details

### Example fix for SearchToolRenderer:

```typescript
// Handle search completion with minimum duration
useEffect(() => {
  if (
    isComplete &&
    searchStartTime !== null &&
    !completionHandledRef.current
  ) {
    completionHandledRef.current = true;
    
    // If stopped, skip intermediate states and complete immediately
    if (stopPacketSeen) {
      // Clear any pending timeouts
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      if (searchedTimeoutRef.current) {
        clearTimeout(searchedTimeoutRef.current);
      }
      
      // Skip "Searched" state, go directly to completion
      setShouldShowAsSearching(false);
      setShouldShowAsSearched(false);
      onComplete();
      return;
    }
    
    // Normal completion flow (not stopped)
    const elapsedTime = Date.now() - searchStartTime;
    const minimumSearchingDuration = animate ? SEARCHING_MIN_DURATION_MS : 0;
    const minimumSearchedDuration = animate ? SEARCHED_MIN_DURATION_MS : 0;

    const handleSearchingToSearched = () => {
      setShouldShowAsSearching(false);
      setShouldShowAsSearched(true);

      searchedTimeoutRef.current = setTimeout(() => {
        setShouldShowAsSearched(false);
        onComplete();
      }, minimumSearchedDuration);
    };

    if (elapsedTime >= minimumSearchingDuration) {
      handleSearchingToSearched();
    } else {
      const remainingTime = minimumSearchingDuration - elapsedTime;
      timeoutRef.current = setTimeout(
        handleSearchingToSearched,
        remainingTime
      );
    }
  }
}, [isComplete, searchStartTime, animate, queries, onComplete, stopPacketSeen]);
```

## Testing

### Manual Testing:
1. Set `TOOL_EXECUTION_DELAY_MS=5000` (from previous PR)
2. Trigger a search query
3. Click stop during execution
4. Verify: Status should stay on "Searching the web" and not flicker to "Searched the web"

### Normal Completion Testing:
1. Remove `TOOL_EXECUTION_DELAY_MS` or set to 0
2. Trigger a search query and let it complete normally
3. Verify: Status should still show "Searching → Searched" transition as before
4. Ensure the fix doesn't break normal completion behavior

## Related PRs

This fix builds on the previous PR that:
- Added `hasSectionEnd()` helper to detect tool completion
- Made shimmering animation conditional on `stopPacketSeen`
- Added `TOOL_EXECUTION_DELAY_MS` for reproducible testing

This PR addresses the status text flickering issue that remains after the shimmering fix.

