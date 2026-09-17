import { act, renderHook } from "@tests/setup/test-utils";
import { useLlmManager } from "@/lib/hooks";
import { ChatSession, ChatSessionSharedStatus } from "@/app/app/interfaces";
import { ReasoningEffortOverride } from "@/lib/languageModels/types";
import {
  updateReasoningEffortForChatSession,
  updateTemperatureOverrideForChatSession,
} from "@/app/app/services/lib";

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: null }),
}));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLLMProviders: () => ({
    llmProviders: [],
    defaultText: undefined,
    isLoading: false,
  }),
}));
jest.mock("@/app/app/services/lib", () => ({
  updateReasoningEffortForChatSession: jest.fn(),
  updateTemperatureOverrideForChatSession: jest.fn(),
}));

function makeSession(
  id: string,
  reasoningEffort: ReasoningEffortOverride | null
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
    current_temperature_override: null,
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
});
