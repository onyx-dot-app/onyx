import { renderHook } from "@testing-library/react";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";

jest.mock("swr", () => ({
  __esModule: true,
  default: () => ({
    data: [
      { name: "typesafe", known_models: [] },
      { name: "openai", known_models: [] },
    ],
    error: undefined,
    mutate: jest.fn(),
  }),
}));

it("offers only chat providers during onboarding", () => {
  const { result } = renderHook(() => useLLMProviderOptions());
  expect(
    result.current.llmProviderOptions?.map((provider) => provider.name)
  ).toEqual(["openai"]);
});
