import { findRegistryModel, resolveProviderName } from "@/lib/indexing";
import type {
  EmbeddingModelSelection,
  EmbeddingModelSpec,
  EmbeddingProviderName,
  ResolvedEmbeddingModelForApply,
} from "@/lib/indexing/types";

export function savedModelSelection(
  currentModel: EmbeddingModelSpec | null,
  currentProviderType: EmbeddingProviderName | null
): EmbeddingModelSelection {
  return {
    model_name: currentModel?.modelName ?? "",
    model_spec: currentModel,
    model_provider: currentProviderType,
  };
}

/**
 * Compared field by field rather than by reference: `initialValues` is rebuilt from a
 * memo whenever the settings query revalidates, so two deep-equal specs routinely
 * arrive as different objects.
 */
export function isSameModelSelection(
  a: EmbeddingModelSelection,
  b: EmbeddingModelSelection
): boolean {
  if (a.model_name !== b.model_name || a.model_provider !== b.model_provider) {
    return false;
  }
  if (a.model_spec === b.model_spec) return true;
  if (!a.model_spec || !b.model_spec) return false;

  return (
    a.model_spec.modelName === b.model_spec.modelName &&
    a.model_spec.modelDim === b.model_spec.modelDim &&
    a.model_spec.normalize === b.model_spec.normalize &&
    (a.model_spec.queryPrefix ?? null) === (b.model_spec.queryPrefix ?? null) &&
    (a.model_spec.passagePrefix ?? null) ===
      (b.model_spec.passagePrefix ?? null)
  );
}

/**
 * The fallbacks here only work for registry models. LiteLLM and Azure models aren't in
 * the registry, so they have to arrive already carrying their own spec and provider.
 */
export function resolveModelForApply(
  selection: EmbeddingModelSelection
): ResolvedEmbeddingModelForApply | null {
  const model = selection.model_spec ?? findRegistryModel(selection.model_name);
  if (!model) return null;

  const providerName =
    selection.model_provider ?? resolveProviderName(selection.model_name, null);

  return { model, providerName };
}
