import { describe, expect, it } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import type { ModelOption } from "@/chat/models";
import { useSelectedModel } from "@/hooks/useSelectedModel";

interface SelectedModelProps {
  chatSessionId: string | null;
  agentId: number | undefined;
  projectId: number | null;
}

const model: ModelOption = {
  modelConfigurationId: 1,
  modelProvider: "OpenAI Prod",
  modelVersion: "gpt-5",
  providerDisplayName: "OpenAI Prod",
  displayName: "GPT-5",
};

function renderSelected(
  chatSessionId: string | null,
  agentId: number | undefined,
  projectId: number | null = null,
) {
  return renderHook((props: SelectedModelProps) => useSelectedModel(props), {
    initialProps: { chatSessionId, agentId, projectId },
  });
}

describe("useSelectedModel", () => {
  it("starts with no pick and records one on select", () => {
    const { result } = renderSelected(null, 0);
    expect(result.current.selectedModel).toBeNull();

    act(() => result.current.selectModel(model));
    expect(result.current.selectedModel).toEqual(model);
  });

  it("clears the pick when moving to a different conversation", () => {
    const { result, rerender } = renderSelected("session-1", 0);
    act(() => result.current.selectModel(model));

    rerender({ chatSessionId: "session-2", agentId: 0, projectId: null });
    expect(result.current.selectedModel).toBeNull();
  });

  // That transition is the send that created the conversation, not a move to another one.
  it("keeps the pick when a new session id arrives for the send that made it", () => {
    const { result, rerender } = renderSelected(null, 0);
    act(() => result.current.selectModel(model));

    rerender({ chatSessionId: "session-1", agentId: 0, projectId: null });
    expect(result.current.selectedModel).toEqual(model);
  });

  it("clears the pick when the agent changes", () => {
    const { result, rerender } = renderSelected(null, 0);
    act(() => result.current.selectModel(model));

    rerender({ chatSessionId: null, agentId: 7, projectId: null });
    expect(result.current.selectedModel).toBeNull();
  });

  it("keeps the pick while the agent is momentarily unresolved", () => {
    const { result, rerender } = renderSelected(null, 0);
    act(() => result.current.selectModel(model));

    rerender({ chatSessionId: null, agentId: undefined, projectId: null });
    expect(result.current.selectedModel).toEqual(model);
  });

  // Both project landing composers sit on a null session and the default agent, so only the
  // project id separates them.
  it("clears the pick when moving between projects", () => {
    const { result, rerender } = renderSelected(null, 0, 1);
    act(() => result.current.selectModel(model));

    rerender({ chatSessionId: null, agentId: 0, projectId: 2 });
    expect(result.current.selectedModel).toBeNull();
  });

  it("clears the pick when leaving a project for a plain chat", () => {
    const { result, rerender } = renderSelected(null, 0, 1);
    act(() => result.current.selectModel(model));

    rerender({ chatSessionId: null, agentId: 0, projectId: null });
    expect(result.current.selectedModel).toBeNull();
  });
});
