---
name: Memoize useLlmManager Hook
overview: Memoize the `useLlmManager` hook's return value and callbacks to prevent unnecessary re-renders of components receiving `llmManager` as a prop.
todos:
  - id: memoize-callbacks
    content: Wrap updateCurrentLlm, updateImageFilesPresent, and updateModelOverrideBasedOnChatSession with useCallback
    status: completed
  - id: memoize-return
    content: Wrap the return object with useMemo and proper dependency array
    status: completed
---

# Memoize useLlm

Manager Hook

## Problem

The `useLlmManager` hook in [web/src/lib/hooks.ts](web/src/lib/hooks.ts) returns a new object literal on every render, causing all downstream components (including `LLMPopover`) to re-render unnecessarily.

## Solution

Memoize the hook's callbacks with `useCallback` and its return value with `useMemo`.

## Changes to `web/src/lib/hooks.ts`

### 1. Wrap callbacks with `useCallback`

The following functions need to be memoized:

- `updateCurrentLlm` (lines 685-688)

- `updateImageFilesPresent` (lines 680-682)
- `updateTemperature` (already exists but needs verification)
- `updateModelOverrideBasedOnChatSession` (lines 695+)

### 2. Wrap return object with `useMemo`

Replace the plain object return (lines 774-789) with a `useMemo` that depends on the actual values:

```typescript
return useMemo(() => ({
  updateModelOverrideBasedOnChatSession,
  currentLlm,
  updateCurrentLlm,
  temperature,
  updateTemperature,
  imageFilesPresent,
  updateImageFilesPresent,
  liveAssistant: liveAssistant ?? null,
  maxTemperature,
  llmProviders,
  isLoadingProviders,
  hasAnyProvider,
}), [
  updateModelOverrideBasedOnChatSession,
  currentLlm,
  updateCurrentLlm,
  temperature,
  updateTemperature,
  imageFilesPresent,
  updateImageFilesPresent,
  liveAssistant,
  maxTemperature,
  llmProviders,
  isLoadingAllProviders,
  isLoadingPersonaProviders,
  personaId,
  hasAnyProvider,
]);
```



## Expected Impact

- `llmManager` reference will only change when its underlying data actually changes

- `LLMPopover` and other components receiving `llmManager` will stop re-rendering on every parent render