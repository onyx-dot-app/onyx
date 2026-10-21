/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";

import {
  useAdminLanguageModels,
  useLanguageModels,
  useLlmDefaults,
} from "@/lib/languageModels/hooks";
import type { DefaultModel } from "@/lib/languageModels/types";

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
  defaultVision: DefaultModel | null,
  defaultChatNaming: DefaultModel | null = null,
  defaultSearchSelection: DefaultModel | null = null
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
      default_search_selection: defaultSearchSelection,
      default_chat_naming: defaultChatNaming,
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

describe.each([
  ["useLanguageModels", useLanguageModels],
  ["useAdminLanguageModels", useAdminLanguageModels],
])("%s task model defaults", (_name, useModels) => {
  beforeEach(() => mockUseSWR.mockReset());

  it("exposes naming and search defaults independently", () => {
    mockProvidersResponse(
      [
        { id: 7, name: null },
        { id: 8, name: "Search provider" },
      ],
      null,
      { provider_id: 7, model_name: "gpt-4o-mini" },
      { provider_id: 8, model_name: "search-mini" }
    );
    const { result } = renderHook(() => useModels());
    expect(result.current.defaultChatNaming).toEqual({
      provider_id: 7,
      model_name: "gpt-4o-mini",
    });
    expect(result.current.defaultSearchSelection).toEqual({
      provider_id: 8,
      model_name: "search-mini",
    });
    expect(result.current).not.toHaveProperty("defaultFast");
  });

  it("does not derive search selection from the naming default", () => {
    mockProvidersResponse([{ id: 7, name: null }], null, {
      provider_id: 7,
      model_name: "gpt-4o-mini",
    });
    const { result } = renderHook(() => useModels());
    expect(result.current.defaultSearchSelection).toBeNull();
  });

  it("does not derive naming from the search default", () => {
    mockProvidersResponse([{ id: 8, name: "Search provider" }], null, null, {
      provider_id: 8,
      model_name: "search-mini",
    });
    const { result } = renderHook(() => useModels());
    expect(result.current.defaultChatNaming).toBeNull();
  });
});
