import {
  buildLlmOptions,
  buildModelSelectOptions,
  filterModelConfigurations,
  fromSelectValue,
  llmOptionKey,
  toSelectValue,
} from "@/lib/languageModels/options";
import type { SelectDivider, SelectOption } from "@opal/components";
import type {
  LLMProviderDescriptor,
  ModelConfiguration,
  ModelOptionProvider,
} from "@/lib/languageModels/types";

function makeModelConfiguration(id: number, name: string): ModelConfiguration {
  return {
    id,
    name,
    is_visible: true,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    effectiveDisplayName: name,
  };
}

function makeProvider(
  id: number,
  name: string,
  provider: string,
  modelConfigurations: ModelConfiguration[]
): LLMProviderDescriptor {
  return {
    id,
    name,
    provider,
    provider_display_name: name,
    model_configurations: modelConfigurations,
  };
}

describe("llmOptionKey", () => {
  it("gives distinct keys to same-named models from different providers", () => {
    const providers = [
      makeProvider(1, "OpenAI Main", "openai", [
        makeModelConfiguration(11, "gpt-4o"),
      ]),
      makeProvider(2, "OpenAI Backup", "openai", [
        makeModelConfiguration(22, "gpt-4o"),
      ]),
    ];

    const keys = buildLlmOptions(providers).map(llmOptionKey);

    expect(keys).toHaveLength(2);
    expect(new Set(keys).size).toBe(2);
  });

  it("keys by model configuration id when present", () => {
    expect(
      llmOptionKey({
        provider: "openai",
        modelName: "gpt-4o",
        modelConfigurationId: 11,
      })
    ).toBe("mc:11");
  });

  it("falls back to provider + model name without an id", () => {
    expect(
      llmOptionKey({
        provider: "openai",
        modelName: "gpt-4o",
        modelConfigurationId: null,
      })
    ).toBe("openai:gpt-4o");
    expect(llmOptionKey({ provider: "openai", modelName: "gpt-4o" })).toBe(
      "openai:gpt-4o"
    );
  });
});

describe("buildLlmOptions", () => {
  it("includes hidden models when requested by an admin picker", () => {
    const hiddenModel = {
      ...makeModelConfiguration(11, "hidden-model"),
      is_visible: false,
    };
    const providers = [makeProvider(1, "OpenAI", "openai", [hiddenModel])];

    expect(buildLlmOptions(providers)).toHaveLength(0);
    expect(buildLlmOptions(providers, undefined, true)).toEqual([
      expect.objectContaining({ modelName: "hidden-model" }),
    ]);
  });
});

describe("filterModelConfigurations", () => {
  const providers: ModelOptionProvider[] = [
    {
      id: 1,
      name: "OpenAI",
      provider: "openai",
      model_configurations: [
        {
          id: 11,
          name: "gpt-4o",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: true,
          supports_reasoning: false,
          effectiveDisplayName: "GPT-4o",
        },
        {
          id: 12,
          name: "o3-mini",
          is_visible: false,
          max_input_tokens: null,
          supports_image_input: false,
          supports_reasoning: true,
          effectiveDisplayName: "o3-mini",
        },
      ],
    },
    {
      id: 2,
      name: null,
      provider: "anthropic",
      model_configurations: [
        {
          id: 21,
          name: "claude-sonnet-4",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: false,
          supports_reasoning: false,
          effectiveDisplayName: "Claude Sonnet 4",
        },
      ],
    },
  ];
  const ids = (list: ModelOptionProvider[]) =>
    list.flatMap((p) => p.model_configurations.map((mc) => mc.id));

  test("drops hidden models by default and keeps them on request", () => {
    expect(ids(filterModelConfigurations(providers))).toEqual([11, 21]);
    expect(
      ids(filterModelConfigurations(providers, { visibleOnly: false }))
    ).toEqual([11, 12, 21]);
  });

  test("keeps only image-input models and drops providers left empty", () => {
    const filtered = filterModelConfigurations(providers, { imageInput: true });
    expect(filtered.map((p) => p.id)).toEqual([1]);
    expect(ids(filtered)).toEqual([11]);
  });

  test("keeps the current value regardless of the other rules", () => {
    expect(
      ids(filterModelConfigurations(providers, { imageInput: true, keep: 12 }))
    ).toEqual([11, 12]);
  });
});

describe("model select options", () => {
  const providers: ModelOptionProvider[] = [
    {
      id: 1,
      name: "OpenAI",
      provider: "openai",
      model_configurations: [
        {
          id: 11,
          name: "gpt-4o",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: true,
          supports_reasoning: false,
          effectiveDisplayName: "GPT-4o",
        },
        {
          id: 12,
          name: "o3-mini",
          is_visible: false,
          max_input_tokens: null,
          supports_image_input: false,
          supports_reasoning: true,
          effectiveDisplayName: "o3-mini",
        },
        {
          name: "unsaved",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: false,
          supports_reasoning: false,
          effectiveDisplayName: "Unsaved",
        },
      ],
    },
    {
      id: 2,
      name: null,
      provider: "anthropic",
      model_configurations: [
        {
          id: 21,
          name: "claude-sonnet-4",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: false,
          supports_reasoning: false,
          effectiveDisplayName: "Claude Sonnet 4",
        },
      ],
    },
  ];

  describe("buildModelSelectOptions", () => {
    // Rows of a divider, or the entry itself when it is a loose row.
    const rowsOf = (entry: SelectOption | SelectDivider) =>
      "options" in entry ? entry.options : [entry];

    test("renders every model given, hidden ones included, under a divider per provider", () => {
      const dividers = buildModelSelectOptions(providers);
      // A nameless provider groups under its product name.
      expect(dividers.map((d) => d.title)).toEqual(["Claude", "OpenAI"]);
      expect(rowsOf(dividers[1]!).map((o) => [o.value, o.title])).toEqual([
        ["11", "GPT-4o"],
        ["12", "o3-mini"],
      ]);
    });

    test("leaves out models without a configuration id", () => {
      const values = buildModelSelectOptions(providers).flatMap((d) =>
        rowsOf(d).map((o) => o.value)
      );
      expect(values).not.toContain("unsaved");
      expect(values).toHaveLength(3);
    });

    test("dividers fold, and grouping can be turned off", () => {
      const grouped = buildModelSelectOptions(providers);
      expect(
        grouped.every((entry) => "options" in entry && entry.foldable)
      ).toBe(true);
      const flat = buildModelSelectOptions(providers, { grouped: false });
      expect(flat.every((entry) => !("options" in entry))).toBe(true);
      expect(
        flat.map((entry) => ("value" in entry ? entry.value : ""))
      ).toEqual(["21", "11", "12"]);
    });

    test("a single provider renders flat: a lone header says nothing", () => {
      const only = providers.filter((p) => p.id === 1);
      const rows = buildModelSelectOptions(only);
      expect(rows.every((entry) => !("options" in entry))).toBe(true);
      expect(rows).toHaveLength(2);
    });

    test("an empty list yields no options", () => {
      expect(buildModelSelectOptions([])).toEqual([]);
    });
  });

  describe("select value helpers", () => {
    test("round-trip a configuration id", () => {
      expect(toSelectValue(11)).toBe("11");
      expect(toSelectValue(null)).toBe("");
      expect(fromSelectValue("11")).toBe(11);
      expect(fromSelectValue("")).toBeNull();
      expect(fromSelectValue("nope")).toBeNull();
    });
  });
});
