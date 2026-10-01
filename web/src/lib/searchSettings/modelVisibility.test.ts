import {
  CLOUD_BASED_PROVIDERS,
  SELF_HOSTED_PROVIDERS,
} from "@/lib/searchSettings/constants";
import {
  findProvider,
  findProviderModel,
  findRegistryModel,
  isBringYourOwnProvider,
  isCloudBased,
  resolveProviderName,
  toEmbeddingModelRef,
  visibleEmbeddingProviders,
} from "@/lib/searchSettings";
import { testEmbedding } from "@/lib/searchSettings/svc";
import { resolveModelForApply } from "@/lib/searchSettings/utils";
import {
  EmbeddingProvider,
  EmbeddingProviderName,
} from "@/lib/searchSettings/types";

const ALL_PROVIDERS = [...CLOUD_BASED_PROVIDERS, ...SELF_HOSTED_PROVIDERS];

function modelNames(providers: EmbeddingProvider[]): string[] {
  return providers.flatMap((p) => p.embeddingModels.map((m) => m.modelName));
}

function groupNames(providers: EmbeddingProvider[]): EmbeddingProviderName[] {
  return providers.map((p) => p.providerName);
}

function visibleGroup(
  providers: EmbeddingProvider[],
  providerName: EmbeddingProviderName
): EmbeddingProvider | undefined {
  return providers.find((p) => p.providerName === providerName);
}

describe("the embedding model registry", () => {
  // Mirrors the SELECTABLE entries of backend/shared_configs/embedding_models.py.
  // The page sends these values as-is to set-new-search-settings, and the
  // backend rejects any mismatch.
  const SELECTABLE = [
    {
      provider: EmbeddingProviderName.IBM,
      modelName: "ibm-granite/granite-embedding-97m-multilingual-r2",
      modelDim: 384,
      normalize: true,
      queryPrefix: "",
      passagePrefix: "",
    },
    {
      provider: EmbeddingProviderName.VOYAGE_SELF_HOSTED,
      modelName: "voyageai/voyage-4-nano",
      modelDim: 2048,
      normalize: true,
      queryPrefix: "Represent the query for retrieving supporting documents: ",
      passagePrefix: "Represent the document for retrieval: ",
    },
    {
      provider: EmbeddingProviderName.NVIDIA,
      modelName: "nvidia/Nemotron-3-Embed-1B-BF16",
      modelDim: 2048,
      normalize: true,
      queryPrefix: "query: ",
      passagePrefix: "passage: ",
    },
    {
      provider: EmbeddingProviderName.COHERE,
      modelName: "embed-v5.0-pro",
      modelDim: 2048,
      normalize: false,
      queryPrefix: "",
      passagePrefix: "",
    },
    {
      provider: EmbeddingProviderName.COHERE,
      modelName: "embed-v5.0-fast",
      modelDim: 2048,
      normalize: false,
      queryPrefix: "",
      passagePrefix: "",
    },
    {
      provider: EmbeddingProviderName.GOOGLE,
      modelName: "gemini-embedding-2",
      modelDim: 3072,
      normalize: false,
      queryPrefix: "",
      passagePrefix: "",
    },
    {
      provider: EmbeddingProviderName.OPENAI,
      modelName: "text-embedding-3-large",
      modelDim: 3072,
      normalize: false,
      queryPrefix: "",
      passagePrefix: "",
    },
    {
      provider: EmbeddingProviderName.OPENAI,
      modelName: "text-embedding-3-small",
      modelDim: 1536,
      normalize: false,
      queryPrefix: "",
      passagePrefix: "",
    },
  ];

  // Mirrors the LEGACY entries of the backend registry. Existing deployments
  // can hold any of them, so the page must keep resolving them.
  const LEGACY = [
    [EmbeddingProviderName.NOMIC, "nomic-ai/nomic-embed-text-v1"],
    [EmbeddingProviderName.MICROSOFT, "intfloat/e5-base-v2"],
    [EmbeddingProviderName.MICROSOFT, "intfloat/e5-small-v2"],
    [EmbeddingProviderName.MICROSOFT, "intfloat/multilingual-e5-base"],
    [EmbeddingProviderName.MICROSOFT, "intfloat/multilingual-e5-small"],
    [EmbeddingProviderName.GTE, "thenlper/gte-small"],
    [EmbeddingProviderName.COHERE, "embed-english-v3.0"],
    [EmbeddingProviderName.COHERE, "embed-english-light-v3.0"],
    [EmbeddingProviderName.COHERE, "embed-v4.0"],
    [EmbeddingProviderName.GOOGLE, "gemini-embedding-001"],
    [EmbeddingProviderName.GOOGLE, "text-embedding-005"],
    [EmbeddingProviderName.GOOGLE, "gemini-embedding-2-preview"],
    [EmbeddingProviderName.GOOGLE, "text-embedding-004"],
    [EmbeddingProviderName.GOOGLE, "textembedding-gecko@003"],
    [EmbeddingProviderName.VOYAGE, "voyage-large-2-instruct"],
    [EmbeddingProviderName.VOYAGE, "voyage-light-2-instruct"],
  ] as const;

  it.each(SELECTABLE)(
    "offers $modelName with the backend spec",
    ({ provider, modelName, ...spec }) => {
      const model = findProviderModel(provider, modelName);

      expect(model).not.toBeNull();
      expect(model?.legacy).toBeFalsy();
      expect({
        modelDim: model?.modelDim,
        normalize: model?.normalize,
        queryPrefix: model?.queryPrefix,
        passagePrefix: model?.passagePrefix,
      }).toEqual(spec);
    }
  );

  it("offers exactly the backend's selectable models", () => {
    const selectable = ALL_PROVIDERS.flatMap((p) =>
      p.embeddingModels.filter((m) => !m.legacy).map((m) => m.modelName)
    );

    expect(selectable.sort()).toEqual(
      SELECTABLE.map((m) => m.modelName).sort()
    );
  });

  it.each(LEGACY)("keeps %s %s as a legacy model", (provider, modelName) => {
    expect(resolveProviderName(modelName, null)).toBe(provider);
    expect(findProviderModel(provider, modelName)?.legacy).toBe(true);
  });

  it("uses each model name once, so a name lookup is unambiguous", () => {
    const names = modelNames(ALL_PROVIDERS);

    expect(new Set(names).size).toBe(names.length);
  });

  it("flags only Nemotron as GPU recommended", () => {
    const gpu = ALL_PROVIDERS.flatMap((p) =>
      p.embeddingModels.filter((m) => m.gpuRecommended).map((m) => m.modelName)
    );

    expect(gpu).toEqual(["nvidia/Nemotron-3-Embed-1B-BF16"]);
  });
});

describe("resolving the new models", () => {
  it("keeps voyage-4-nano self-hosted, so it never reaches the Voyage API", () => {
    const providerName = resolveProviderName("voyageai/voyage-4-nano", null);

    expect(providerName).toBe(EmbeddingProviderName.VOYAGE_SELF_HOSTED);
    expect(providerName).not.toBe(EmbeddingProviderName.VOYAGE);
    // setNewSearchSettings sends provider_type=null for non-cloud groups.
    expect(isCloudBased(providerName)).toBe(false);
    expect(findProvider(providerName).displayName).toBe("Voyage AI");
  });

  it("resolves a staged embed-v5.0-pro to Cohere at 2048 dimensions", () => {
    const resolved = resolveModelForApply({
      model_name: "embed-v5.0-pro",
      model_spec: null,
      model_provider: null,
    });

    expect(resolved?.providerName).toBe(EmbeddingProviderName.COHERE);
    expect(resolved?.model.modelDim).toBe(2048);
    expect(isCloudBased(EmbeddingProviderName.COHERE)).toBe(true);
  });

  it("resolves the fresh-install default to the IBM group", () => {
    const ref = toEmbeddingModelRef(
      "ibm-granite/granite-embedding-97m-multilingual-r2",
      null
    );

    expect(ref.providerName).toBe(EmbeddingProviderName.IBM);
    expect(isCloudBased(ref.providerName)).toBe(false);
  });

  it("still resolves the removed-then-restored models instead of Custom", () => {
    expect(resolveProviderName("text-embedding-004", null)).toBe(
      EmbeddingProviderName.GOOGLE
    );
    expect(resolveProviderName("textembedding-gecko@003", null)).toBe(
      EmbeddingProviderName.GOOGLE
    );
    expect(resolveProviderName("thenlper/gte-small", null)).toBe(
      EmbeddingProviderName.GTE
    );
  });
});

describe("the models the picker lists", () => {
  const GRANITE_CURRENT = toEmbeddingModelRef(
    "ibm-granite/granite-embedding-97m-multilingual-r2",
    null
  );

  it("hides every legacy model that is not current", () => {
    const visible = [
      ...visibleEmbeddingProviders(CLOUD_BASED_PROVIDERS, GRANITE_CURRENT),
      ...visibleEmbeddingProviders(SELF_HOSTED_PROVIDERS, GRANITE_CURRENT),
    ];

    for (const name of modelNames(visible)) {
      expect(findRegistryModel(name)?.legacy).toBeFalsy();
    }
    expect(modelNames(visible)).not.toContain("nomic-ai/nomic-embed-text-v1");
    expect(modelNames(visible)).not.toContain("embed-english-v3.0");
  });

  it("hides legacy models when there is no current model", () => {
    const visible = visibleEmbeddingProviders(SELF_HOSTED_PROVIDERS, null);

    expect(groupNames(visible)).toEqual([
      EmbeddingProviderName.IBM,
      EmbeddingProviderName.VOYAGE_SELF_HOSTED,
      EmbeddingProviderName.NVIDIA,
    ]);
  });

  it("drops groups left empty, but keeps LiteLLM and Azure", () => {
    const visible = visibleEmbeddingProviders(
      CLOUD_BASED_PROVIDERS,
      GRANITE_CURRENT
    );

    // Cohere stays first: its v5 models are selectable.
    expect(groupNames(visible)).toEqual([
      EmbeddingProviderName.COHERE,
      EmbeddingProviderName.OPENAI,
      EmbeddingProviderName.GOOGLE,
      EmbeddingProviderName.LITELLM,
      EmbeddingProviderName.AZURE,
    ]);
    expect(
      visible
        .filter((p) => isBringYourOwnProvider(p.providerName))
        .every((p) => p.embeddingModels.length === 0)
    ).toBe(true);
  });

  it("shows a current legacy self-hosted model in its own group", () => {
    const visible = visibleEmbeddingProviders(
      SELF_HOSTED_PROVIDERS,
      toEmbeddingModelRef("intfloat/e5-base-v2", null)
    );

    expect(
      modelNames([visibleGroup(visible, EmbeddingProviderName.MICROSOFT)!])
    ).toEqual(["intfloat/e5-base-v2"]);
    expect(visibleGroup(visible, EmbeddingProviderName.NOMIC)).toBeUndefined();
  });

  it("shows a current legacy cloud model next to the selectable ones", () => {
    const visible = visibleEmbeddingProviders(
      CLOUD_BASED_PROVIDERS,
      toEmbeddingModelRef("embed-english-v3.0", EmbeddingProviderName.COHERE)
    );

    expect(
      modelNames([visibleGroup(visible, EmbeddingProviderName.COHERE)!])
    ).toEqual(["embed-v5.0-pro", "embed-v5.0-fast", "embed-english-v3.0"]);
  });

  it("keeps a group whose only models are legacy while one of them is current", () => {
    const visible = visibleEmbeddingProviders(
      CLOUD_BASED_PROVIDERS,
      toEmbeddingModelRef(
        "voyage-large-2-instruct",
        EmbeddingProviderName.VOYAGE
      )
    );

    expect(
      modelNames([visibleGroup(visible, EmbeddingProviderName.VOYAGE)!])
    ).toEqual(["voyage-large-2-instruct"]);
  });

  it("keeps an empty group with saved credentials, so they can be disconnected", () => {
    const visible = visibleEmbeddingProviders(
      CLOUD_BASED_PROVIDERS,
      GRANITE_CURRENT,
      new Set([EmbeddingProviderName.VOYAGE])
    );

    expect(
      visibleGroup(visible, EmbeddingProviderName.VOYAGE)?.embeddingModels
    ).toEqual([]);
  });

  it("keeps the group of a current model that is not in the registry", () => {
    const visible = visibleEmbeddingProviders(
      CLOUD_BASED_PROVIDERS,
      toEmbeddingModelRef("voyage-3", EmbeddingProviderName.VOYAGE)
    );

    expect(
      visibleGroup(visible, EmbeddingProviderName.VOYAGE)?.embeddingModels
    ).toEqual([]);
  });

  it("does not bring back a legacy model for an Azure deployment of the same name", () => {
    const azureCurrent = toEmbeddingModelRef(
      "embed-english-v3.0",
      EmbeddingProviderName.AZURE
    );

    const visible = visibleEmbeddingProviders(
      CLOUD_BASED_PROVIDERS,
      azureCurrent
    );

    expect(modelNames(visible)).not.toContain("embed-english-v3.0");
    // Nor does it borrow the registry entry for its description.
    expect(
      findProviderModel(azureCurrent.providerName, azureCurrent.modelName)
    ).toBeNull();
  });

  it("does not borrow the OpenAI entry for an Azure deployment labelled like it", () => {
    expect(
      findProviderModel(EmbeddingProviderName.AZURE, "text-embedding-3-large")
    ).toBeNull();
    expect(
      findProviderModel(EmbeddingProviderName.OPENAI, "text-embedding-3-large")
        ?.modelDim
    ).toBe(3072);
  });

  it("returns the same provider object when it hides nothing", () => {
    const visible = visibleEmbeddingProviders(
      CLOUD_BASED_PROVIDERS,
      GRANITE_CURRENT
    );

    expect(visibleGroup(visible, EmbeddingProviderName.OPENAI)).toBe(
      visibleGroup(CLOUD_BASED_PROVIDERS, EmbeddingProviderName.OPENAI)
    );
  });
});

describe("the credential test model", () => {
  const originalFetch = global.fetch;
  let sentBodies: Record<string, unknown>[];

  beforeEach(() => {
    sentBodies = [];
    global.fetch = jest.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        sentBodies.push(JSON.parse(String(init?.body)));
        return new Response("{}", { status: 200 });
      }
    );
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  async function probe(providerType: string, modelName: string) {
    await testEmbedding({
      provider_type: providerType,
      modelName,
      apiKey: "key",
      apiUrl: null,
      apiVersion: null,
      deploymentName: null,
    });
    return sentBodies[0]?.model_name;
  }

  it("tests the model the admin is connecting for", async () => {
    expect(await probe("openai", "text-embedding-3-large")).toBe(
      "text-embedding-3-large"
    );
    sentBodies = [];
    expect(await probe("cohere", "embed-v5.0-pro")).toBe("embed-v5.0-pro");
  });

  it("falls back to a model every OpenAI key can call", async () => {
    expect(await probe("openai", "")).toBe("text-embedding-3-small");
  });
});
