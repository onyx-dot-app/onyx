// Bun port of useLLMProviders.test.ts. Lives as `.bun-test.ts` so Jest's
// `*.test.ts` matcher ignores it. Demonstrates the jest → bun:test API mapping:
//   jest.mock(...)            → mock.module(...)
//   jest.fn()                 → mock()
//   jest.MockedFunction<T>    → Mock<T>
//   jest.spyOn(obj, "method") → spyOn(obj, "method")  (unchanged elsewhere)
import { beforeEach, describe, expect, mock, test, type Mock } from "bun:test";
import useSWR from "swr";
import { useLLMProviders } from "@/hooks/useLanguageModels";
import { errorHandlingFetcher } from "@/lib/fetcher";

mock.module("swr", () => ({
  __esModule: true,
  default: mock(),
}));

mock.module("@/lib/fetcher", () => ({
  errorHandlingFetcher: mock(),
}));

const mockUseSWR = useSWR as unknown as Mock<typeof useSWR>;

describe("useLLMProviders", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
  });

  test("uses public providers endpoint when personaId is not provided", () => {
    const mockMutate = mock();
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
    const mockMutate = mock();
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
      mutate: mock(),
      isValidating: false,
    } as any);

    const result = useLLMProviders();

    expect(result.isLoading).toBe(false);
    expect(result.error).toBeInstanceOf(Error);
  });
});
