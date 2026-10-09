import { describe, expect, it } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import { useDeepResearchToggle } from "@/hooks/useDeepResearchToggle";

function renderToggle(
  chatSessionId: string | null,
  agentId: number | undefined,
) {
  return renderHook(
    (props: { chatSessionId: string | null; agentId: number | undefined }) =>
      useDeepResearchToggle(props),
    { initialProps: { chatSessionId, agentId } },
  );
}

describe("useDeepResearchToggle", () => {
  it("starts off and toggles", () => {
    const { result } = renderToggle(null, 0);
    expect(result.current.deepResearchEnabled).toBe(false);

    act(() => result.current.toggleDeepResearch());
    expect(result.current.deepResearchEnabled).toBe(true);

    act(() => result.current.toggleDeepResearch());
    expect(result.current.deepResearchEnabled).toBe(false);
  });

  it("preserves the flag when the landing gets its new session", () => {
    const { result, rerender } = renderToggle(null, 0);
    act(() => result.current.toggleDeepResearch());

    rerender({ chatSessionId: "session-1", agentId: 0 });
    expect(result.current.deepResearchEnabled).toBe(true);
  });

  it("resets when switching between existing sessions", () => {
    const { result, rerender } = renderToggle("session-1", 0);
    act(() => result.current.toggleDeepResearch());

    rerender({ chatSessionId: "session-2", agentId: 0 });
    expect(result.current.deepResearchEnabled).toBe(false);
  });

  it("resets when leaving a session for a new chat", () => {
    const { result, rerender } = renderToggle("session-1", 0);
    act(() => result.current.toggleDeepResearch());

    rerender({ chatSessionId: null, agentId: 0 });
    expect(result.current.deepResearchEnabled).toBe(false);
  });

  it("resets when the agent changes", () => {
    const { result, rerender } = renderToggle(null, 0);
    act(() => result.current.toggleDeepResearch());

    rerender({ chatSessionId: null, agentId: 7 });
    expect(result.current.deepResearchEnabled).toBe(false);
  });

  it("ignores an agent id that is not resolved yet", () => {
    const { result, rerender } = renderToggle(null, undefined);
    act(() => result.current.toggleDeepResearch());

    // agents finish loading — the first known id is not a switch
    rerender({ chatSessionId: null, agentId: 7 });
    expect(result.current.deepResearchEnabled).toBe(true);
  });

  it("still resets when a switch passes through an unresolved agent", () => {
    const { result, rerender } = renderToggle(null, 7);
    act(() => result.current.toggleDeepResearch());

    rerender({ chatSessionId: null, agentId: undefined });
    rerender({ chatSessionId: null, agentId: 9 });
    expect(result.current.deepResearchEnabled).toBe(false);
  });

  it("keeps the flag across the send that creates a session with an unresolved persona", () => {
    const { result, rerender } = renderToggle(null, 7);
    act(() => result.current.toggleDeepResearch());

    // the session exists but isn't in the sessions list yet, so its persona is unknown…
    rerender({ chatSessionId: "session-1", agentId: undefined });
    expect(result.current.deepResearchEnabled).toBe(true);

    // …and resolves to the same agent once the list refreshes
    rerender({ chatSessionId: "session-1", agentId: 7 });
    expect(result.current.deepResearchEnabled).toBe(true);
  });
});
