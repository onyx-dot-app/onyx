import { renderHook, act } from "@testing-library/react";
import useMultiModelChat from "@/hooks/useMultiModelChat";
import { LlmManager } from "@/lib/hooks";
import { SelectedModel } from "@/refresh-components/popovers/ModelSelector";

// Mock buildLlmOptions — hook uses it internally for initialization.
// Tests here focus on CRUD operations, not the initialization side-effect.
jest.mock("@/refresh-components/popovers/LLMPopover", () => ({
  buildLlmOptions: jest.fn(() => []),
}));

const makeLlmManager = (): LlmManager =>
  ({
    llmProviders: [],
    currentLlm: { modelName: null, provider: null },
    isLoadingProviders: false,
  }) as unknown as LlmManager;

const makeModel = (provider: string, modelName: string): SelectedModel => ({
  name: provider,
  provider,
  modelName,
  displayName: `${provider}/${modelName}`,
});

const GPT4 = makeModel("openai", "gpt-4");
const CLAUDE = makeModel("anthropic", "claude-opus-4-6");
const GEMINI = makeModel("google", "gemini-pro");
const GPT4_TURBO = makeModel("openai", "gpt-4-turbo");

// ---------------------------------------------------------------------------
// addModel
// ---------------------------------------------------------------------------

describe("addModel", () => {
  it("adds a model to an empty selection", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
    });

    expect(result.current.selectedModels).toHaveLength(1);
    expect(result.current.selectedModels[0]).toEqual(GPT4);
  });

  it("does not add a duplicate model", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(GPT4); // duplicate
    });

    expect(result.current.selectedModels).toHaveLength(1);
  });

  it("enforces MAX_MODELS (3) cap", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(CLAUDE);
      result.current.addModel(GEMINI);
      result.current.addModel(GPT4_TURBO); // should be ignored
    });

    expect(result.current.selectedModels).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------
// removeModel
// ---------------------------------------------------------------------------

describe("removeModel", () => {
  it("removes a model by index", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(CLAUDE);
    });

    act(() => {
      result.current.removeModel(0); // remove GPT4
    });

    expect(result.current.selectedModels).toHaveLength(1);
    expect(result.current.selectedModels[0]).toEqual(CLAUDE);
  });

  it("handles out-of-range index gracefully", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
    });

    act(() => {
      result.current.removeModel(99); // no-op
    });

    expect(result.current.selectedModels).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// replaceModel
// ---------------------------------------------------------------------------

describe("replaceModel", () => {
  it("replaces the model at the given index", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(CLAUDE);
    });

    act(() => {
      result.current.replaceModel(0, GEMINI);
    });

    expect(result.current.selectedModels[0]).toEqual(GEMINI);
    expect(result.current.selectedModels[1]).toEqual(CLAUDE);
  });

  it("does not replace with a model already selected at another index", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(CLAUDE);
    });

    act(() => {
      result.current.replaceModel(0, CLAUDE); // CLAUDE is already at index 1
    });

    // Should be a no-op — GPT4 stays at index 0
    expect(result.current.selectedModels[0]).toEqual(GPT4);
  });
});

// ---------------------------------------------------------------------------
// isMultiModelActive
// ---------------------------------------------------------------------------

describe("isMultiModelActive", () => {
  it("is false with zero models", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));
    expect(result.current.isMultiModelActive).toBe(false);
  });

  it("is false with exactly one model", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
    });

    expect(result.current.isMultiModelActive).toBe(false);
  });

  it("is true with two or more models", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(CLAUDE);
    });

    expect(result.current.isMultiModelActive).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// buildLlmOverrides
// ---------------------------------------------------------------------------

describe("buildLlmOverrides", () => {
  it("returns empty array when no models selected", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));
    expect(result.current.buildLlmOverrides()).toEqual([]);
  });

  it("maps selectedModels to LLMOverride format", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(CLAUDE);
    });

    const overrides = result.current.buildLlmOverrides();

    expect(overrides).toHaveLength(2);
    expect(overrides[0]).toEqual({
      model_provider: "openai",
      model_version: "gpt-4",
      display_name: "openai/gpt-4",
    });
    expect(overrides[1]).toEqual({
      model_provider: "anthropic",
      model_version: "claude-opus-4-6",
      display_name: "anthropic/claude-opus-4-6",
    });
  });
});

// ---------------------------------------------------------------------------
// clearModels
// ---------------------------------------------------------------------------

describe("clearModels", () => {
  it("empties the selection", () => {
    const { result } = renderHook(() => useMultiModelChat(makeLlmManager()));

    act(() => {
      result.current.addModel(GPT4);
      result.current.addModel(CLAUDE);
    });

    act(() => {
      result.current.clearModels();
    });

    expect(result.current.selectedModels).toHaveLength(0);
    expect(result.current.isMultiModelActive).toBe(false);
  });
});
