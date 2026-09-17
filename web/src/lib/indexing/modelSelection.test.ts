import {
  isSameModelSelection,
  resolveModelForApply,
  savedModelSelection,
} from "@/lib/indexing/utils";
import {
  EmbeddingModelSpec,
  EmbeddingProviderName,
} from "@/lib/indexing/types";

/** A deployment the static registry has never heard of, which is the whole point. */
function deployment(modelName: string): EmbeddingModelSpec {
  return {
    modelName,
    modelDim: 1536,
    normalize: false,
    queryPrefix: "",
    passagePrefix: "",
  };
}

describe("the model the form loads with", () => {
  it("keeps an Azure deployment on its own provider and dimension when the label collides with the OpenAI registry", () => {
    const seeded = savedModelSelection(
      deployment("text-embedding-3-large"),
      EmbeddingProviderName.AZURE
    );

    const resolved = resolveModelForApply(seeded);

    expect(resolved?.providerName).toBe(EmbeddingProviderName.AZURE);
    // The OpenAI registry entry of the same name is 3072 — sending it would
    // build the new index at the wrong width.
    expect(resolved?.model.modelDim).toBe(1536);
  });

  it("resolves a LiteLLM deployment whose label is in no registry", () => {
    const seeded = savedModelSelection(
      deployment("text-embedding-ada-002"),
      EmbeddingProviderName.LITELLM
    );

    expect(resolveModelForApply(seeded)).toEqual({
      model: deployment("text-embedding-ada-002"),
      providerName: EmbeddingProviderName.LITELLM,
    });
  });

  it("resolves a self-hosted model to its display bucket, which is only a name away", () => {
    const seeded = savedModelSelection(
      {
        modelName: "nomic-ai/nomic-embed-text-v1",
        modelDim: 768,
        normalize: true,
      },
      null
    );

    const resolved = resolveModelForApply(seeded);

    // Self-hosted rows carry no provider, so the name picks the bucket. That is safe
    // here because the bucket only chooses an icon and a heading.
    expect(resolved?.providerName).toBe(EmbeddingProviderName.NOMIC);
    expect(resolved?.model.modelDim).toBe(768);
  });
});

describe("the model the user stages", () => {
  it("takes a registry model's provider and spec from the registry", () => {
    const resolved = resolveModelForApply({
      model_name: "text-embedding-3-large",
      model_spec: null,
      model_provider: null,
    });

    expect(resolved?.providerName).toBe(EmbeddingProviderName.OPENAI);
    expect(resolved?.model.modelDim).toBe(3072);
  });

  it("takes a LiteLLM model's provider and spec from the selection", () => {
    const staged = deployment("my-proxy-model");

    expect(
      resolveModelForApply({
        model_name: staged.modelName,
        model_spec: staged,
        model_provider: EmbeddingProviderName.LITELLM,
      })
    ).toEqual({ model: staged, providerName: EmbeddingProviderName.LITELLM });
  });

  it("returns null for an unknown model with no spec", () => {
    expect(
      resolveModelForApply({
        model_name: "some/unregistered-model",
        model_spec: null,
        model_provider: null,
      })
    ).toBeNull();
  });
});

describe("comparing one selection to another", () => {
  const saved = savedModelSelection(
    deployment("my-deployment"),
    EmbeddingProviderName.AZURE
  );

  it("treats a rebuilt but identical selection as unchanged", () => {
    // The settings query revalidates and the memo hands back a fresh object.
    const rebuilt = savedModelSelection(
      deployment("my-deployment"),
      EmbeddingProviderName.AZURE
    );

    expect(rebuilt.model_spec).not.toBe(saved.model_spec);
    expect(isSameModelSelection(saved, rebuilt)).toBe(true);
  });

  it("spots a respec that keeps the same name", () => {
    const respecced = {
      ...saved,
      model_spec: { ...deployment("my-deployment"), modelDim: 3072 },
    };

    expect(isSameModelSelection(saved, respecced)).toBe(false);
  });

  it("spots a prefix change that keeps the same name and dimension", () => {
    const respecced = {
      ...saved,
      model_spec: { ...deployment("my-deployment"), queryPrefix: "query: " },
    };

    expect(isSameModelSelection(saved, respecced)).toBe(false);
  });

  it("spots a staged registry model replacing the saved spec", () => {
    expect(isSameModelSelection(saved, { ...saved, model_spec: null })).toBe(
      false
    );
  });

  it("spots a different name and a different provider", () => {
    expect(isSameModelSelection(saved, { ...saved, model_name: "other" })).toBe(
      false
    );
    expect(
      isSameModelSelection(saved, {
        ...saved,
        model_provider: EmbeddingProviderName.LITELLM,
      })
    ).toBe(false);
  });

  it("treats two spec-less selections as unchanged", () => {
    const registry = {
      model_name: "text-embedding-3-large",
      model_spec: null,
      model_provider: null,
    };

    expect(isSameModelSelection(registry, { ...registry })).toBe(true);
  });
});
