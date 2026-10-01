import {
  CLOUD_BASED_PROVIDERS,
  CUSTOM_PROVIDER,
  SELF_HOSTED_PROVIDERS,
} from "@/lib/searchSettings/constants";
import {
  EmbeddingModel,
  EmbeddingModelRef,
  EmbeddingProvider,
  EmbeddingProviderName,
  IndexSettingsTranslator,
} from "@/lib/searchSettings/types";

/**
 * Total lookup of an {@link EmbeddingProvider} by its `providerName`.
 * Covers the cloud registry, the self-hosted registry, and the synthetic
 * `CUSTOM_PROVIDER` — every value of `EmbeddingProviderName` resolves to a
 * registered entry, so the return type is non-null. The trailing `throw`
 * is unreachable as long as the enum and registries stay in sync.
 */
export function findProvider(
  providerName: EmbeddingProviderName
): EmbeddingProvider {
  for (const p of CLOUD_BASED_PROVIDERS) {
    if (p.providerName === providerName) return p;
  }
  for (const p of SELF_HOSTED_PROVIDERS) {
    if (p.providerName === providerName) return p;
  }
  if (providerName === EmbeddingProviderName.CUSTOM) return CUSTOM_PROVIDER;
  throw new Error(`Unknown embedding provider: ${providerName}`);
}

/**
 * `true` iff the resolved `providerName` corresponds to a cloud-routed
 * provider — i.e. credentials are managed via API keys, the row should
 * have an editable creds modal, and the backend should route through a
 * cloud SDK rather than the local model server. Returns `false` for
 * self-hosted buckets (e.g. `IBM`, `VOYAGE_SELF_HOSTED`, `NOMIC`) and `CUSTOM`.
 */
export function isCloudBased(providerName: EmbeddingProviderName): boolean {
  return CLOUD_BASED_PROVIDERS.some((p) => p.providerName === providerName);
}

/**
 * `true` for the cloud providers that have no registry models (LiteLLM,
 * Azure). The admin enters the model spec in the connect modal. The picker
 * shows them in the "bring your own" section, not in the main list.
 */
export function isBringYourOwnProvider(
  providerName: EmbeddingProviderName
): boolean {
  return (
    providerName === EmbeddingProviderName.LITELLM ||
    providerName === EmbeddingProviderName.AZURE
  );
}

/**
 * Find an {@link EmbeddingModel} spec by `modelName` across both registries.
 * Returns `null` for models that aren't pre-registered (e.g. custom
 * self-hosted models added through the modal — those carry their own spec
 * in form state and don't need a registry hit).
 */
export function findRegistryModel(modelName: string): EmbeddingModel | null {
  for (const p of CLOUD_BASED_PROVIDERS) {
    const m = p.embeddingModels.find((m) => m.modelName === modelName);
    if (m) return m;
  }
  for (const p of SELF_HOSTED_PROVIDERS) {
    const m = p.embeddingModels.find((m) => m.modelName === modelName);
    if (m) return m;
  }
  return null;
}

/**
 * Find the registry model of one provider group. Unlike `findRegistryModel`,
 * a LiteLLM or Azure deployment whose label equals a registry name (e.g.
 * `text-embedding-3-large`) does not match the OpenAI entry.
 */
export function findProviderModel(
  providerName: EmbeddingProviderName,
  modelName: string
): EmbeddingModel | null {
  return (
    findProvider(providerName).embeddingModels.find(
      (m) => m.modelName === modelName
    ) ?? null
  );
}

/** Identify a persisted model by its display group and name. */
export function toEmbeddingModelRef(
  modelName: string,
  providerTypeHint: EmbeddingProviderName | null
): EmbeddingModelRef {
  return {
    modelName,
    providerName: resolveProviderName(modelName, providerTypeHint),
  };
}

/** `true` if `ref` names this registry model of this provider group. */
function isSameModel(
  ref: EmbeddingModelRef | null,
  provider: EmbeddingProvider,
  model: EmbeddingModel
): boolean {
  return (
    ref !== null &&
    ref.providerName === provider.providerName &&
    ref.modelName === model.modelName
  );
}

/**
 * The provider groups and models the picker lists (and searches).
 *
 * - A legacy model is kept only while it is the current model. The match uses
 *   the provider AND the name, so an Azure deployment labelled like a registry
 *   model does not bring back that model.
 * - A group left with no models is dropped, except:
 *   - Bring-your-own groups (LiteLLM, Azure). They have no registry models by
 *     design.
 *   - The group of the current model. It lists a current model that is not in
 *     the registry.
 *   - Groups in `keepProviders` (e.g. providers with saved credentials). Their
 *     header holds the only Disconnect and Edit credentials buttons.
 *
 * Returns the same provider object when nothing in it is hidden.
 */
export function visibleEmbeddingProviders(
  providers: EmbeddingProvider[],
  current: EmbeddingModelRef | null,
  keepProviders: ReadonlySet<EmbeddingProviderName> = new Set()
): EmbeddingProvider[] {
  const visible: EmbeddingProvider[] = [];
  for (const provider of providers) {
    if (isBringYourOwnProvider(provider.providerName)) {
      visible.push(provider);
      continue;
    }
    const models = provider.embeddingModels.filter(
      (m) => !m.legacy || isSameModel(current, provider, m)
    );
    if (
      models.length === 0 &&
      current?.providerName !== provider.providerName &&
      !keepProviders.has(provider.providerName)
    ) {
      continue;
    }
    visible.push(
      models.length === provider.embeddingModels.length
        ? provider
        : { ...provider, embeddingModels: models }
    );
  }
  return visible;
}

/** Translated registry description, undefined without a key. */
export function embeddingModelDescription(
  model: EmbeddingModel | null | undefined,
  t: IndexSettingsTranslator,
  appName: string
): string | undefined {
  return model?.descriptionKey
    ? t(model.descriptionKey, { appName })
    : undefined;
}

/**
 * NOTE(@raunakab): This function is a CONTEXTUAL workaround for a deeper data
 * model issue that should — and hopefully WILL — be properly addressed on the
 * backend in the very near future. Until that schema change lands, every code
 * path that needs to ask "which provider does this embedding model belong to?"
 * MUST funnel through this resolver so the hack stays in exactly one place
 * and is trivial to delete once the schema catches up.
 *
 * THE PROBLEM
 * ───────────
 * The `search_settings` table currently identifies an embedding model with
 * two fields:
 *   • `provider_type: EmbeddingProvider | NULL` — a NULLABLE enum where the
 *     null value is overloaded to mean "self-hosted (any kind)".
 *   • `model_name: STRING` — an opaque identifier (e.g.
 *     `"intfloat/e5-base-v2"`, `"text-embedding-3-large"`). Note that the
 *     `<org>/<repo>` shape is NOT parsed; the backend hands the full string
 *     to HuggingFace's `SentenceTransformer` loader as-is.
 *
 * The null-overload conflates two ORTHOGONAL questions:
 *
 *   1. Should the backend route through a cloud API or the local model
 *      server? (Currently encoded as `provider_type IS NULL` vs `IS NOT
 *      NULL` — see the routing branch in
 *      `backend/onyx/natural_language_processing/search_nlp_models.py`.)
 *
 *   2. Which logical bucket does this model belong to for UI purposes —
 *      icon, modal selection, displayName? (Currently UNREPRESENTED in the
 *      schema for self-hosted models: IBM vs Nomic vs Microsoft vs custom
 *      must be inferred from `model_name` by walking a frontend registry.)
 *
 * Because (2) is unrepresented in the schema, the frontend has historically
 * resorted to one of two hacks:
 *   • Walking the static registry by `model_name` to recover the bucket.
 *   • Tracking parallel form state (e.g. a `custom_model` flag) to remember
 *     "this came from the Add Custom Model modal."
 *
 * Both are brittle. The first reclassifies historical rows whenever the
 * registry is edited. The second leaks UI-only context into form state and
 * forces every read site to re-implement the discrimination — exactly the
 * pattern this resolver is designed to eliminate.
 *
 * THE PROPER FIX (NOT YET LANDED)
 * ───────────────────────────────
 * The intended schema is three NON-NULLABLE columns:
 *   • `cloud_based: BOOLEAN NOT NULL` — answers (1) explicitly.
 *   • `provider_type: STRING NOT NULL` — answers (2) explicitly, with values
 *     covering every cloud provider PLUS dedicated values for self-hosted
 *     buckets (e.g. `"nomic"`, `"microsoft"`, `"custom"`).
 *   • `model_name: STRING NOT NULL` — unchanged, opaque identifier.
 *
 * Landing that requires:
 *   • Adding `SELF_HOSTED`-style values to `EmbeddingProvider` in
 *     `backend/shared_configs/enums.py`.
 *   • An Alembic migration to backfill existing nulls and add the NOT NULL
 *     constraint.
 *   • Switching the routing branch in
 *     `backend/onyx/natural_language_processing/search_nlp_models.py` from
 *     `provider_type is None` to a `cloud_based`-driven check.
 *   • Updating Pydantic models / response schemas so the frontend can read
 *     `provider_type` directly off the model instead of guessing.
 *
 * WHAT THIS FUNCTION DOES UNTIL THEN
 * ──────────────────────────────────
 * Given the two existing backend fields (`modelName` plus an optional
 * non-null `providerTypeHint` — i.e. the row's `provider_type` if the
 * backend already filled it in), this resolver SIMULATES the proper schema
 * by deriving the canonical `EmbeddingProviderName`, including the
 * synthetic self-hosted bucket values that the backend cannot currently
 * persist (e.g. `IBM`, `NVIDIA`, `NOMIC`, `CUSTOM`).
 *
 * Resolution rules, in order:
 *
 *   1. If `providerTypeHint` is non-null, trust it. The backend has already
 *      told us which cloud provider this row belongs to and there's nothing
 *      ambiguous to resolve.
 *
 *   2. Otherwise (`provider_type IS NULL` on the backend, OR we're working
 *      with a freshly-staged model that hasn't been persisted yet), walk
 *      `CLOUD_BASED_PROVIDERS` for a `modelName` match. This branch is
 *      defensive — it shouldn't fire for backend-sourced rows since cloud
 *      models always have a non-null `provider_type` — but it's needed when
 *      the resolver runs over Formik state at submit time, where no hint
 *      is yet available.
 *
 *   3. Otherwise, walk `SELF_HOSTED_PROVIDERS` for a `modelName` match and
 *      return that bucket's `providerName` (e.g. `IBM`, `MICROSOFT`).
 *
 *   4. Otherwise — the model isn't in any registry — fall through to
 *      `EmbeddingProviderName.CUSTOM`. This is the "user added a custom
 *      self-hosted model via the modal" case.
 *
 * This is a HACK. Delete this function (and the synthetic enum values it
 * depends on) the moment the backend schema migration lands.
 */
export function resolveProviderName(
  modelName: string,
  providerTypeHint: EmbeddingProviderName | null
): EmbeddingProviderName {
  if (providerTypeHint) return providerTypeHint;
  for (const provider of CLOUD_BASED_PROVIDERS) {
    if (provider.embeddingModels.some((m) => m.modelName === modelName)) {
      return provider.providerName;
    }
  }
  for (const provider of SELF_HOSTED_PROVIDERS) {
    if (provider.embeddingModels.some((m) => m.modelName === modelName)) {
      return provider.providerName;
    }
  }
  return EmbeddingProviderName.CUSTOM;
}
