import useSWR from "swr";
import { useLLMProviders } from "@/hooks/useLLMProviders";
import { errorHandlingFetcher } from "@/lib/fetcher";

jest.mock("swr", () => ({
  __esModule: true,
  default: jest.fn(),
}));

jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: jest.fn(),
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;

describe("useLLMProviders", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
  });

  test("uses public providers endpoint when personaId is not provided", () => {
    const mockMutate = jest.fn();
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      mutate: mockMutate,
      isValidating: false,
    } as any);

    const result = useLLMProviders();

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/llm/provider",
      errorHandlingFetcher,
      expect.objectContaining({
        revalidateOnFocus: false,
        dedupingInterval: 60000,
      })
    );
    expect(result.isLoading).toBe(true);
    expect(result.refetch).toBe(mockMutate);
  });

  test("uses persona-specific providers endpoint when personaId is provided", () => {
    const mockMutate = jest.fn();
    const providers = [{ name: "Persona Provider" }];
    mockUseSWR.mockReturnValue({
      data: { providers, default_text: null, default_vision: null },
      error: undefined,
      mutate: mockMutate,
      isValidating: false,
    } as any);

    const result = useLLMProviders(42);

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/llm/persona/42/providers",
      errorHandlingFetcher,
      expect.objectContaining({
        revalidateOnFocus: false,
        dedupingInterval: 60000,
      })
    );
    expect(result.llmProviders).toBe(providers);
    expect(result.isLoading).toBe(false);
    expect(result.refetch).toBe(mockMutate);
  });

  test("reports not loading when SWR returns an error", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: new Error("request failed"),
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const result = useLLMProviders();

    expect(result.isLoading).toBe(false);
    expect(result.error).toBeInstanceOf(Error);
  });
});
