import { useSyncExternalStore } from "react";
import { act, renderHook, waitFor } from "@tests/setup/test-utils";
import { useLlmManager } from "@/lib/hooks";
import { ChatSession, ChatSessionSharedStatus } from "@/app/app/types";
import { ReasoningEffortOverride } from "@/lib/languageModels/types";
import {
  updateReasoningEffortForChatSession,
  updateTemperatureOverrideForChatSession,
} from "@/app/app/services/lib";

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: null }),
}));
jest.mock("@/lib/languageModels/hooks", () => {
  const empty = () => ({
    llmProviders: [],
    defaultText: undefined,
    isLoading: false,
  });
  return { useLanguageModels: empty, useLanguageModelsForAgent: empty };
});
jest.mock("@/app/app/services/lib", () => ({
  updateReasoningEffortForChatSession: jest.fn(),
  updateTemperatureOverrideForChatSession: jest.fn(),
}));

function makeSession(
  id: string,
  reasoningEffort: ReasoningEffortOverride | null,
  temperatureOverride: number | null = null
): ChatSession {
  return {
    id,
    name: "",
    persona_id: 0,
    time_created: "",
    time_updated: "",
    shared_status: ChatSessionSharedStatus.Private,
    project_id: null,
    current_alternate_model: "",
    current_temperature_override: temperatureOverride,
    current_reasoning_effort_override: reasoningEffort,
  };
}

interface HookProps {
  session?: ChatSession;
}

describe("useLlmManager override persistence", () => {
  beforeEach(() => {
    const ok = { ok: true, status: 200 } as Response;
    jest.mocked(updateReasoningEffortForChatSession).mockResolvedValue(ok);
    jest.mocked(updateTemperatureOverrideForChatSession).mockResolvedValue(ok);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test("a persistOverrides reference taken before the selection writes the current choice", async () => {
    const { result } = renderHook(() => useLlmManager());
    // The send path can hold a reference from an earlier render.
    const persistOverrides = result.current.persistOverrides;

    act(() => result.current.updateReasoningEffort("high"));
    await act(async () => {
      await persistOverrides("session-1");
    });

    expect(updateReasoningEffortForChatSession).toHaveBeenCalledWith(
      "session-1",
      "high"
    );
  });

  test("a session persisted while unbound keeps the selection once it is adopted", async () => {
    const { result, rerender } = renderHook(
      (props: HookProps) => useLlmManager(props.session),
      { initialProps: {} }
    );

    act(() => result.current.updateReasoningEffort("high"));
    await act(async () => {
      await result.current.persistOverrides("session-1");
    });

    // The placeholder for the new session carries no override yet.
    rerender({ session: makeSession("session-1", null) });
    expect(result.current.reasoningEffort).toBe("high");

    // Another session still reads its own row.
    rerender({ session: makeSession("session-2", "low") });
    expect(result.current.reasoningEffort).toBe("low");

    // Coming back reads the row too, not the old local choice.
    rerender({ session: makeSession("session-1", null) });
    expect(result.current.reasoningEffort).toBeNull();
  });

  test.each([
    ["with a saved override", 0.8, 0.8],
    ["without a saved override", null, 0.5],
  ])(
    "opening a session %s reads it without writing",
    async (_label, saved, expected) => {
      const { result, rerender } = renderHook(
        (props: HookProps) => useLlmManager(props.session),
        { initialProps: {} }
      );

      // Writes run on a promise chain, so let it drain.
      await act(async () =>
        rerender({ session: makeSession("session-1", "high", saved) })
      );

      expect(result.current.temperature).toBe(expected);
      expect(result.current.reasoningEffort).toBe("high");
      expect(updateTemperatureOverrideForChatSession).not.toHaveBeenCalled();
      expect(updateReasoningEffortForChatSession).not.toHaveBeenCalled();
    }
  );

  test("a Claude session saved above Claude's maximum opens bounded without writing", async () => {
    const { result, rerender } = renderHook(
      (props: HookProps) => useLlmManager(props.session),
      { initialProps: {} }
    );

    await act(async () =>
      rerender({
        session: {
          ...makeSession("session-1", null, 1.5),
          current_alternate_model: "Claude__anthropic__claude-sonnet",
        },
      })
    );

    expect(result.current.maxTemperature).toBe(1);
    expect(result.current.temperature).toBe(1);
    expect(updateTemperatureOverrideForChatSession).not.toHaveBeenCalled();
  });

  test("switching to an Anthropic model bounds the temperature without writing", async () => {
    const session = makeSession("session-1", null, 0.8);
    const { result } = renderHook(() => useLlmManager(session));
    const claude = { name: "a", provider: "anthropic", modelName: "claude" };
    const gpt = { name: "o", provider: "openai", modelName: "gpt" };

    await act(async () => result.current.updateCurrentLlm(gpt));
    await act(async () => result.current.updateTemperature(1.5));
    jest.mocked(updateTemperatureOverrideForChatSession).mockClear();

    await act(async () => result.current.updateCurrentLlm(claude));
    expect(result.current.temperature).toBe(1);
    expect(updateTemperatureOverrideForChatSession).not.toHaveBeenCalled();

    // The send hands off the bounded value, not the stored choice.
    await act(async () => result.current.persistOverrides("session-1"));
    expect(updateTemperatureOverrideForChatSession).toHaveBeenCalledWith(
      "session-1",
      1
    );
  });

  test("a choice made before the first send reaches the session the send creates", async () => {
    // The chat-session list the page reads, which the send publishes the
    // new session to.
    let published: ChatSession | undefined;
    const listeners = new Set<() => void>();
    const { result } = renderHook(() =>
      useLlmManager(
        useSyncExternalStore(
          (listener) => {
            listeners.add(listener);
            return () => listeners.delete(listener);
          },
          () => published
        )
      )
    );
    act(() => result.current.updateTemperature(1.3));
    act(() => result.current.updateReasoningEffort("high"));

    // Outside act, so React schedules the render as it does in the browser.
    Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", false);
    try {
      // The send's synchronous tail after createChatSession resolves:
      // publish the placeholder, navigate, then persist the overrides.
      published = makeSession("session-1", null);
      listeners.forEach((listener) => listener());
      await result.current.persistOverrides("session-1");
      await waitFor(() => expect(result.current.hasBoundSession).toBe(true));
    } finally {
      Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
    }

    expect(updateTemperatureOverrideForChatSession).toHaveBeenCalledWith(
      "session-1",
      1.3
    );
    expect(updateReasoningEffortForChatSession).toHaveBeenCalledWith(
      "session-1",
      "high"
    );
    // What the next send carries.
    expect(result.current.temperature).toBe(1.3);
    expect(result.current.hasTemperatureOverride).toBe(true);
    expect(result.current.reasoningEffort).toBe("high");
  });
});
