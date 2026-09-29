/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";

import { useLlmDefaults } from "@/lib/languageModels/hooks";

const mockUseSWR = jest.fn();

jest.mock("next/navigation", () => ({
  usePathname: () => "/admin/configuration/llm",
}));

jest.mock("swr", () => ({
  __esModule: true,
  default: (...args: unknown[]) => mockUseSWR(...args),
}));

interface ProviderFixture {
  id: number;
  name: string | null;
}

function mockProvidersResponse(
  providers: ProviderFixture[],
  defaultVision: { provider_id: number; model_name: string } | null
): void {
  mockUseSWR.mockReturnValue({
    data: {
      providers: providers.map((p) => ({
        id: p.id,
        name: p.name,
        provider: "openai",
        provider_display_name: p.name ?? "OpenAI",
        model_configurations: [
          {
            id: p.id * 100,
            name: "gpt-4o",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: true,
            supports_reasoning: false,
          },
        ],
      })),
      default_text: null,
      default_vision: defaultVision,
      default_chat_naming: null,
      default_craft: null,
    },
    error: undefined,
    mutate: jest.fn(),
  });
}

describe("useLlmDefaults", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
  });

  it("resolves a default whose provider has no display name", () => {
    // `llm_provider.name` is nullable and well-known providers are routinely
    // saved without one. Requiring a name here dropped a configured default and
    // the admin pickers rendered it as unset.
    mockProvidersResponse([{ id: 7, name: null }], {
      provider_id: 7,
      model_name: "gpt-4o",
    });

    const { result } = renderHook(() => useLlmDefaults());

    expect(result.current.defaultVision).toEqual({
      providerId: 7,
      modelName: "gpt-4o",
    });
  });

  it("resolves a default whose provider has a display name", () => {
    mockProvidersResponse([{ id: 7, name: "Azure Prod" }], {
      provider_id: 7,
      model_name: "gpt-4o",
    });

    const { result } = renderHook(() => useLlmDefaults());

    expect(result.current.defaultVision?.providerId).toBe(7);
  });

  it("returns null when the stored provider is no longer in the list", () => {
    mockProvidersResponse([{ id: 7, name: "Azure Prod" }], {
      provider_id: 999,
      model_name: "gpt-4o",
    });

    const { result } = renderHook(() => useLlmDefaults());

    expect(result.current.defaultVision).toBeNull();
  });

  it("keys off provider id, not position, when display names collide", () => {
    mockProvidersResponse(
      [
        { id: 43, name: "Daily" },
        { id: 54, name: "Daily" },
      ],
      { provider_id: 54, model_name: "gpt-4o" }
    );

    const { result } = renderHook(() => useLlmDefaults());

    expect(result.current.defaultVision?.providerId).toBe(54);
  });
});
