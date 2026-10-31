/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";
import useSWR from "swr";
import {
  useLanguageModels,
  useLanguageModelsForAgent,
  useVisionLanguageModels,
} from "@/lib/languageModels/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";

jest.mock("swr", () => ({
  __esModule: true,
  default: jest.fn(),
}));

jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: jest.fn(),
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;

describe("useLanguageModels", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
  });

  test("uses public providers endpoint when personaId is not provided", async () => {
    const mockMutate = jest.fn();
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      mutate: mockMutate,
      isValidating: false,
    } as any);

    const { result } = renderHook(() => useLanguageModels());

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/llm/provider",
      errorHandlingFetcher,
      expect.objectContaining({
        revalidateOnFocus: false,
        dedupingInterval: 60000,
      })
    );
    expect(result.current.isLoading).toBe(true);
    await result.current.refetch();
    expect(mockMutate).toHaveBeenCalled();
  });

  test("uses persona-specific providers endpoint when personaId is provided", async () => {
    const mockMutate = jest.fn();
    const providers = [{ name: "Persona Provider", model_configurations: [] }];
    mockUseSWR.mockReturnValue({
      data: { providers, default_text: null, default_vision: null },
      error: undefined,
      mutate: mockMutate,
      isValidating: false,
    } as any);

    const { result } = renderHook(() => useLanguageModelsForAgent(42));

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/llm/persona/42/providers",
      errorHandlingFetcher,
      expect.objectContaining({
        revalidateOnFocus: false,
        dedupingInterval: 60000,
      })
    );
    expect(result.current.llmProviders).toEqual(providers);
    expect(result.current.isLoading).toBe(false);
    await result.current.refetch();
    expect(mockMutate).toHaveBeenCalled();
  });

  test("useVisionLanguageModels keeps only visible image-input models", () => {
    const model = (
      name: string,
      is_visible: boolean,
      supports_image_input: boolean
    ) => ({ name, is_visible, supports_image_input });
    const providers = [
      {
        name: "Mixed",
        model_configurations: [
          model("vision-visible", true, true),
          model("vision-hidden", false, true),
          model("text-only", true, false),
        ],
      },
      {
        name: "Text Only",
        model_configurations: [model("text-a", true, false)],
      },
      {
        name: "Hidden Vision",
        model_configurations: [model("vision-b", false, true)],
      },
    ];
    mockUseSWR.mockReturnValue({
      data: { providers, default_text: null, default_vision: null },
      error: undefined,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const { result } = renderHook(() => useVisionLanguageModels());

    expect(result.current.llmProviders).toHaveLength(1);
    expect(result.current.llmProviders?.[0]?.name).toBe("Mixed");
    expect(
      result.current.llmProviders?.[0]?.model_configurations.map(
        (mc) => mc.name
      )
    ).toEqual(["vision-visible"]);
  });

  test("reports not loading when SWR returns an error", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: new Error("request failed"),
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const { result } = renderHook(() => useLanguageModels());

    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });
});
