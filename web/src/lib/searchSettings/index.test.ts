import {
  CLOUD_BASED_PROVIDERS,
  SELF_HOSTED_PROVIDERS,
} from "@/lib/searchSettings/constants";
import {
  defaultTestModelName,
  findProviderModel,
  findRegistryModel,
  isBringYourOwnProvider,
  isCloudBased,
  visibleEmbeddingProviders,
} from "@/lib/searchSettings";
import {
  EmbeddingProvider,
  EmbeddingProviderName,
} from "@/lib/searchSettings/types";

const ALL_PROVIDERS = [...CLOUD_BASED_PROVIDERS, ...SELF_HOSTED_PROVIDERS];

function modelNames(providers: EmbeddingProvider[]): string[] {
  return providers.flatMap((p) => p.embeddingModels.map((m) => m.modelName));
}

function groupModels(
  providers: EmbeddingProvider[],
  providerName: EmbeddingProviderName
): string[] | undefined {
  return providers
    .find((p) => p.providerName === providerName)
    ?.embeddingModels.map((m) => m.modelName);
}

// backend/tests/unit/shared_configs/test_web_embedding_model_registry_parity.py
// pins the model specs and legacy flags. These tests cover what it cannot.
describe("the embedding model registry", () => {
  it("uses each model name once, so a name lookup is unambiguous", () => {
    const names = modelNames(ALL_PROVIDERS);

    expect(new Set(names).size).toBe(names.length);
  });

  it("never routes a self-hosted group to a cloud API", () => {
    for (const provider of SELF_HOSTED_PROVIDERS) {
      expect(isCloudBased(provider.providerName)).toBe(false);
    }
  });

  it("has a selectable model to test the credentials of each cloud provider", () => {
    for (const provider of CLOUD_BASED_PROVIDERS) {
      if (isBringYourOwnProvider(provider.providerName)) continue;
      const modelName = defaultTestModelName(provider.providerName);

      expect(
        findProviderModel(provider.providerName, modelName)?.legacy
      ).toBeFalsy();
    }
  });
});

describe("visibleEmbeddingProviders", () => {
  const GRANITE = {
    providerName: EmbeddingProviderName.IBM,
    modelName: "ibm-granite/granite-embedding-97m-multilingual-r2",
  };
  // No cloud group of the registry has only legacy models, so build one.
  const LEGACY_ONLY_VOYAGE = CLOUD_BASED_PROVIDERS.map((p) =>
    p.providerName === EmbeddingProviderName.VOYAGE
      ? { ...p, embeddingModels: p.embeddingModels.filter((m) => m.legacy) }
      : p
  );

  it("hides legacy models that are not current and drops the groups it empties", () => {
    const visible = visibleEmbeddingProviders(ALL_PROVIDERS, null);

    for (const name of modelNames(visible)) {
      expect(findRegistryModel(name)?.legacy).toBeFalsy();
    }
    expect(
      visibleEmbeddingProviders(SELF_HOSTED_PROVIDERS, null).map(
        (p) => p.providerName
      )
    ).toEqual([
      EmbeddingProviderName.IBM,
      EmbeddingProviderName.VOYAGE_SELF_HOSTED,
      EmbeddingProviderName.NVIDIA,
    ]);
  });

  it("keeps the bring-your-own groups, which have no registry models", () => {
    expect(
      visibleEmbeddingProviders(LEGACY_ONLY_VOYAGE, GRANITE).map(
        (p) => p.providerName
      )
    ).toEqual([
      EmbeddingProviderName.COHERE,
      EmbeddingProviderName.OPENAI,
      EmbeddingProviderName.GOOGLE,
      EmbeddingProviderName.LITELLM,
      EmbeddingProviderName.AZURE,
      EmbeddingProviderName.BIFROST,
      EmbeddingProviderName.OPENAI_COMPATIBLE,
    ]);
  });

  it("shows a current legacy model in its own group, after the selectable ones", () => {
    const selfHosted = visibleEmbeddingProviders(SELF_HOSTED_PROVIDERS, {
      providerName: EmbeddingProviderName.MICROSOFT,
      modelName: "intfloat/e5-base-v2",
    });

    expect(groupModels(selfHosted, EmbeddingProviderName.MICROSOFT)).toEqual([
      "intfloat/e5-base-v2",
    ]);
    expect(
      groupModels(selfHosted, EmbeddingProviderName.NOMIC)
    ).toBeUndefined();

    const cloud = visibleEmbeddingProviders(CLOUD_BASED_PROVIDERS, {
      providerName: EmbeddingProviderName.COHERE,
      modelName: "embed-english-v3.0",
    });

    expect(groupModels(cloud, EmbeddingProviderName.COHERE)).toEqual([
      "embed-v5.0-pro",
      "embed-v5.0-fast",
      "embed-english-v3.0",
    ]);
  });

  it("keeps an emptied group with saved credentials, so they can be disconnected", () => {
    const visible = visibleEmbeddingProviders(
      LEGACY_ONLY_VOYAGE,
      GRANITE,
      new Set([EmbeddingProviderName.VOYAGE])
    );

    expect(groupModels(visible, EmbeddingProviderName.VOYAGE)).toEqual([]);
  });

  it("matches the current model on provider and name", () => {
    // An Azure deployment labelled like a legacy Cohere model.
    const visible = visibleEmbeddingProviders(CLOUD_BASED_PROVIDERS, {
      providerName: EmbeddingProviderName.AZURE,
      modelName: "embed-english-v3.0",
    });

    expect(modelNames(visible)).not.toContain("embed-english-v3.0");
    expect(
      findProviderModel(EmbeddingProviderName.AZURE, "text-embedding-3-large")
    ).toBeNull();
  });
});
