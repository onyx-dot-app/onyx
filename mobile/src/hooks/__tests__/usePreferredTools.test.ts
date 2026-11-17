import { describe, expect, it } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import { usePreferredTools } from "@/hooks/usePreferredTools";

interface PreferredProps {
  chatSessionId: string | null;
  agentId: number | undefined;
  projectId: number | null;
}

function renderPreferred(
  chatSessionId: string | null,
  agentId: number | undefined,
  projectId: number | null = null,
) {
  return renderHook((props: PreferredProps) => usePreferredTools(props), {
    initialProps: { chatSessionId, agentId, projectId },
  });
}

describe("usePreferredTools", () => {
  it("starts unpreferred and selects on toggle", () => {
    const { result } = renderPreferred(null, 0);
    expect(result.current.preferredToolId).toBeNull();

    act(() => result.current.togglePreferredTool(3));
    expect(result.current.preferredToolId).toBe(3);
  });

  it("clears the preference when the same tool is tapped again", () => {
    const { result } = renderPreferred(null, 0);
    act(() => result.current.togglePreferredTool(3));
    act(() => result.current.togglePreferredTool(3));
    expect(result.current.preferredToolId).toBeNull();
  });

  it("replaces rather than accumulates when another tool is tapped", () => {
    const { result } = renderPreferred(null, 0);
    act(() => result.current.togglePreferredTool(3));
    act(() => result.current.togglePreferredTool(7));
    expect(result.current.preferredToolId).toBe(7);
  });

  it("clears on demand", () => {
    const { result } = renderPreferred(null, 0);
    act(() => result.current.togglePreferredTool(3));
    act(() => result.current.clearPreferredTool());
    expect(result.current.preferredToolId).toBeNull();
  });

  it("preserves the preference when the landing gets its new session", () => {
    const { result, rerender } = renderPreferred(null, 0);
    act(() => result.current.togglePreferredTool(3));

    rerender({ chatSessionId: "session-1", agentId: 0, projectId: null });
    expect(result.current.preferredToolId).toBe(3);
  });

  it("resets when switching between existing sessions", () => {
    const { result, rerender } = renderPreferred("session-1", 0);
    act(() => result.current.togglePreferredTool(3));

    rerender({ chatSessionId: "session-2", agentId: 0, projectId: null });
    expect(result.current.preferredToolId).toBeNull();
  });

  it("resets when the agent changes", () => {
    const { result, rerender } = renderPreferred(null, 0);
    act(() => result.current.togglePreferredTool(3));

    rerender({ chatSessionId: null, agentId: 7, projectId: null });
    expect(result.current.preferredToolId).toBeNull();
  });

  it("keeps the preference across the send that creates a session with an unresolved persona", () => {
    const { result, rerender } = renderPreferred(null, 7);
    act(() => result.current.togglePreferredTool(3));

    rerender({
      chatSessionId: "session-1",
      agentId: undefined,
      projectId: null,
    });
    expect(result.current.preferredToolId).toBe(3);

    rerender({ chatSessionId: "session-1", agentId: 7, projectId: null });
    expect(result.current.preferredToolId).toBe(3);
  });

  it("still resets when a switch passes through an unresolved agent", () => {
    const { result, rerender } = renderPreferred(null, 7);
    act(() => result.current.togglePreferredTool(3));

    rerender({ chatSessionId: null, agentId: undefined, projectId: null });
    rerender({ chatSessionId: null, agentId: 9, projectId: null });
    expect(result.current.preferredToolId).toBeNull();
  });

  it("clears the preference when the composer crosses into a project", () => {
    const { result, rerender } = renderPreferred(null, 0, null);
    act(() => result.current.togglePreferredTool(5));

    rerender({ chatSessionId: null, agentId: 0, projectId: 5 });
    expect(result.current.preferredToolId).toBeNull();
  });

  it("clears the preference when moving between two projects", () => {
    const { result, rerender } = renderPreferred(null, 0, 5);
    act(() => result.current.togglePreferredTool(5));

    rerender({ chatSessionId: null, agentId: 0, projectId: 6 });
    expect(result.current.preferredToolId).toBeNull();
  });

  it("keeps the preference while the project scope is unchanged", () => {
    const { result, rerender } = renderPreferred(null, 0, 5);
    act(() => result.current.togglePreferredTool(5));

    rerender({ chatSessionId: null, agentId: 0, projectId: 5 });
    expect(result.current.preferredToolId).toBe(5);
  });
});
