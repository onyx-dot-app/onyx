import { describe, expect, it } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import { useForcedTools } from "@/hooks/useForcedTools";

interface ForcedProps {
  chatSessionId: string | null;
  agentId: number | undefined;
  projectId: number | null;
}

function renderForced(
  chatSessionId: string | null,
  agentId: number | undefined,
  projectId: number | null = null,
) {
  return renderHook((props: ForcedProps) => useForcedTools(props), {
    initialProps: { chatSessionId, agentId, projectId },
  });
}

describe("useForcedTools", () => {
  it("starts unforced and forces on toggle", () => {
    const { result } = renderForced(null, 0);
    expect(result.current.forcedToolId).toBeNull();

    act(() => result.current.toggleForcedTool(3));
    expect(result.current.forcedToolId).toBe(3);
  });

  it("releases the force when the same tool is tapped again", () => {
    const { result } = renderForced(null, 0);
    act(() => result.current.toggleForcedTool(3));
    act(() => result.current.toggleForcedTool(3));
    expect(result.current.forcedToolId).toBeNull();
  });

  it("replaces rather than accumulates when another tool is tapped", () => {
    const { result } = renderForced(null, 0);
    act(() => result.current.toggleForcedTool(3));
    act(() => result.current.toggleForcedTool(7));
    expect(result.current.forcedToolId).toBe(7);
  });

  it("clears on demand", () => {
    const { result } = renderForced(null, 0);
    act(() => result.current.toggleForcedTool(3));
    act(() => result.current.clearForcedTool());
    expect(result.current.forcedToolId).toBeNull();
  });

  it("preserves the force when the landing gets its new session", () => {
    const { result, rerender } = renderForced(null, 0);
    act(() => result.current.toggleForcedTool(3));

    rerender({ chatSessionId: "session-1", agentId: 0, projectId: null });
    expect(result.current.forcedToolId).toBe(3);
  });

  it("resets when switching between existing sessions", () => {
    const { result, rerender } = renderForced("session-1", 0);
    act(() => result.current.toggleForcedTool(3));

    rerender({ chatSessionId: "session-2", agentId: 0, projectId: null });
    expect(result.current.forcedToolId).toBeNull();
  });

  it("resets when the agent changes", () => {
    const { result, rerender } = renderForced(null, 0);
    act(() => result.current.toggleForcedTool(3));

    rerender({ chatSessionId: null, agentId: 7, projectId: null });
    expect(result.current.forcedToolId).toBeNull();
  });

  it("keeps the force across the send that creates a session with an unresolved persona", () => {
    const { result, rerender } = renderForced(null, 7);
    act(() => result.current.toggleForcedTool(3));

    rerender({
      chatSessionId: "session-1",
      agentId: undefined,
      projectId: null,
    });
    expect(result.current.forcedToolId).toBe(3);

    rerender({ chatSessionId: "session-1", agentId: 7, projectId: null });
    expect(result.current.forcedToolId).toBe(3);
  });

  it("still resets when a switch passes through an unresolved agent", () => {
    const { result, rerender } = renderForced(null, 7);
    act(() => result.current.toggleForcedTool(3));

    rerender({ chatSessionId: null, agentId: undefined, projectId: null });
    rerender({ chatSessionId: null, agentId: 9, projectId: null });
    expect(result.current.forcedToolId).toBeNull();
  });

  it("releases the force when the composer crosses into a project", () => {
    const { result, rerender } = renderForced(null, 0, null);
    act(() => result.current.toggleForcedTool(5));

    rerender({ chatSessionId: null, agentId: 0, projectId: 5 });
    expect(result.current.forcedToolId).toBeNull();
  });

  it("releases the force when moving between two projects", () => {
    const { result, rerender } = renderForced(null, 0, 5);
    act(() => result.current.toggleForcedTool(5));

    rerender({ chatSessionId: null, agentId: 0, projectId: 6 });
    expect(result.current.forcedToolId).toBeNull();
  });

  it("keeps the force while the project scope is unchanged", () => {
    const { result, rerender } = renderForced(null, 0, 5);
    act(() => result.current.toggleForcedTool(5));

    rerender({ chatSessionId: null, agentId: 0, projectId: 5 });
    expect(result.current.forcedToolId).toBe(5);
  });
});
