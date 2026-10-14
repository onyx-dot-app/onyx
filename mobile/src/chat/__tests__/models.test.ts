import { describe, expect, it } from "@jest/globals";

import {
  buildModelOptions,
  groupModelOptions,
  isSameModelOption,
  resolveDefaultOption,
  toLlmOverride,
  type LlmProvider,
  type ModelConfiguration,
} from "@/chat/models";

function model(
  overrides: Partial<ModelConfiguration> = {},
): ModelConfiguration {
  return {
    id: 1,
    name: "gpt-5",
    is_visible: true,
    display_name: null,
    custom_display_name: null,
    ...overrides,
  };
}

function provider(overrides: Partial<LlmProvider> = {}): LlmProvider {
  return {
    id: 10,
    name: "OpenAI Prod",
    provider: "openai",
    provider_display_name: "OpenAI",
    model_configurations: [model()],
    ...overrides,
  };
}

describe("buildModelOptions", () => {
  it("drops models the admin has hidden", () => {
    const options = buildModelOptions([
      provider({
        model_configurations: [
          model({ id: 1, name: "shown" }),
          model({ id: 2, name: "hidden", is_visible: false }),
        ],
      }),
    ]);
    expect(options.map((o) => o.modelVersion)).toEqual(["shown"]);
  });

  it("keeps a hidden model when it is the one currently selected", () => {
    const options = buildModelOptions(
      [
        provider({
          model_configurations: [
            model({ id: 2, name: "hidden", is_visible: false }),
          ],
        }),
      ],
      "hidden",
    );
    expect(options.map((o) => o.modelVersion)).toEqual(["hidden"]);
  });

  it("sends the provider's instance name, not its vendor slug", () => {
    const [option] = buildModelOptions([provider()]);
    expect(option?.modelProvider).toBe("OpenAI Prod");
  });

  it("prefers a custom display name, then the display name, then the raw name", () => {
    const options = buildModelOptions([
      provider({
        model_configurations: [
          model({ id: 1, name: "raw" }),
          model({ id: 2, name: "b", display_name: "Display" }),
          model({
            id: 3,
            name: "c",
            display_name: "Display",
            custom_display_name: "Custom",
          }),
        ],
      }),
    ]);
    expect(options.map((o) => o.displayName)).toEqual([
      "raw",
      "Display",
      "Custom",
    ]);
  });

  it("keeps a model that has no configuration row, so it can still be sent by name", () => {
    const options = buildModelOptions([
      provider({
        model_configurations: [model({ id: null, name: "unsaved" })],
      }),
    ]);
    expect(options).toHaveLength(1);
    expect(options[0]?.modelConfigurationId).toBeNull();
  });

  it("de-duplicates models that repeat across providers", () => {
    const options = buildModelOptions([
      provider({ id: 10, model_configurations: [model({ id: 1 })] }),
      provider({ id: 11, model_configurations: [model({ id: 1 })] }),
    ]);
    expect(options).toHaveLength(1);
  });
});

describe("resolveDefaultOption", () => {
  it("resolves the default from its provider id and model name", () => {
    const providers = [
      provider({
        id: 10,
        name: "OpenAI Prod",
        model_configurations: [model({ id: 1, name: "gpt-5" })],
      }),
    ];
    const options = buildModelOptions(providers);
    const resolved = resolveDefaultOption(
      providers,
      { provider_id: 10, model_name: "gpt-5" },
      options,
    );
    expect(resolved?.modelConfigurationId).toBe(1);
  });

  it("returns null when the named default is not in the list", () => {
    const providers = [provider()];
    const options = buildModelOptions(providers);
    expect(
      resolveDefaultOption(
        providers,
        { provider_id: 10, model_name: "missing" },
        options,
      ),
    ).toBeNull();
    expect(resolveDefaultOption(providers, null, options)).toBeNull();
  });

  it("does not match a same-named model belonging to another provider", () => {
    const providers = [
      provider({
        id: 10,
        name: "First",
        model_configurations: [model({ id: 1, name: "gpt-5" })],
      }),
      provider({
        id: 11,
        name: "Second",
        model_configurations: [model({ id: 2, name: "gpt-5" })],
      }),
    ];
    const options = buildModelOptions(providers);
    const resolved = resolveDefaultOption(
      providers,
      { provider_id: 11, model_name: "gpt-5" },
      options,
    );
    expect(resolved?.modelProvider).toBe("Second");
  });
});

describe("groupModelOptions", () => {
  it("groups by provider while preserving the original order", () => {
    const options = buildModelOptions([
      provider({ id: 10, name: "A", model_configurations: [model({ id: 1 })] }),
      provider({ id: 11, name: "B", model_configurations: [model({ id: 2 })] }),
      provider({ id: 12, name: "A", model_configurations: [model({ id: 3 })] }),
    ]);
    expect(
      groupModelOptions(options).map((g) => g.providerDisplayName),
    ).toEqual(["A", "B"]);
    expect(groupModelOptions(options)[0]?.options).toHaveLength(2);
  });
});

describe("isSameModelOption", () => {
  const base = buildModelOptions([provider()])[0]!;

  it("compares by configuration id when both have one", () => {
    expect(isSameModelOption(base, { ...base, displayName: "renamed" })).toBe(
      true,
    );
    expect(isSameModelOption(base, { ...base, modelConfigurationId: 99 })).toBe(
      false,
    );
  });

  it("falls back to the provider and model name when there is no id", () => {
    const noId = { ...base, modelConfigurationId: null };
    expect(isSameModelOption(noId, { ...noId })).toBe(true);
    expect(isSameModelOption(noId, { ...noId, modelVersion: "other" })).toBe(
      false,
    );
  });
});

describe("toLlmOverride", () => {
  it("sends the id alongside the provider and model names", () => {
    expect(toLlmOverride(buildModelOptions([provider()])[0]!)).toEqual({
      model_configuration_id: 1,
      model_provider: "OpenAI Prod",
      model_version: "gpt-5",
    });
  });
});
