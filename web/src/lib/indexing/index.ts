import { SvgHardDrive } from "@opal/icons";
import {
  SvgAzure,
  SvgCohere,
  SvgGoogle,
  SvgLitellm,
  SvgMicrosoft,
  SvgNomic,
  SvgOpenai,
  SvgVoyage,
} from "@opal/logos";
import {
  EmbeddingModel,
  EmbeddingProvider,
  EmbeddingProviderName,
} from "@/lib/indexing/interfaces";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

// ═══════════════════════════════════════════════════════════════════════════
// Embedding
// ═══════════════════════════════════════════════════════════════════════════

export const CLOUD_BASED_PROVIDERS: EmbeddingProvider[] = [
  {
    providerName: EmbeddingProviderName.COHERE,
    displayName: "Cohere",
    icon: SvgCohere,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://dashboard.cohere.ai/api-keys",
    costslink: "https://cohere.com/pricing",
    embeddingModels: [
      {
        modelName: "embed-english-v3.0",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Cohere's English embedding model. Good performance for English-language tasks.",
      },
      {
        modelName: "embed-english-light-v3.0",
        modelDim: 384,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Cohere's lightweight English embedding model. Faster and more efficient for simpler tasks.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.OPENAI,
    displayName: "OpenAI",
    icon: SvgOpenai,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://platform.openai.com/api-keys",
    costslink: "https://openai.com/pricing",
    embeddingModels: [
      {
        modelName: "text-embedding-3-large",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "OpenAI's large embedding model. Best performance, but more expensive.",
      },
      {
        modelName: "text-embedding-3-small",
        modelDim: 1536,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "OpenAI's newer, more efficient embedding model. Good balance of performance and cost.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.GOOGLE,
    displayName: "Google",
    icon: SvgGoogle,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://console.cloud.google.com/apis/credentials",
    costslink: "https://cloud.google.com/vertex-ai/pricing",
    embeddingModels: [
      {
        modelName: "gemini-embedding-001",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description: "Google's Gemini embedding model. Powerful and efficient.",
      },
      {
        modelName: "text-embedding-005",
        modelDim: 768,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description: "Smaller, lighter-weight embedding model from Google.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.VOYAGE,
    displayName: "Voyage",
    icon: SvgVoyage,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://www.voyageai.com/dashboard",
    costslink: "https://www.voyageai.com/pricing",
    deprecated: true,
    embeddingModels: [
      {
        modelName: "voyage-large-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Voyage's large embedding model. High performance with instruction fine-tuning.",
      },
      {
        modelName: "voyage-light-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Voyage's lightweight embedding model. Good balance of performance and efficiency.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.LITELLM,
    displayName: "LiteLLM",
    icon: SvgLitellm,
    apiLink: "https://docs.litellm.ai/docs/proxy/quick_start",
    embeddingModels: [],
  },
  {
    providerName: EmbeddingProviderName.AZURE,
    displayName: "Azure",
    icon: SvgAzure,
    apiLink:
      "https://docs.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource",
    costslink:
      "https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai/",
    embeddingModels: [],
  },
];

export const SELF_HOSTED_PROVIDERS: EmbeddingProvider[] = [
  {
    providerName: EmbeddingProviderName.NOMIC,
    displayName: "Nomic",
    icon: SvgNomic,
    docsLink: "https://huggingface.co/nomic-ai",
    embeddingModels: [
      {
        modelName: "nomic-ai/nomic-embed-text-v1",
        modelDim: 768,
        normalize: true,
        queryPrefix: "search_query: ",
        passagePrefix: "search_document: ",
        description:
          "Nomic's embedding model specialized for retrieval, similarity, clustering and classification.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.MICROSOFT,
    displayName: "Microsoft",
    icon: SvgMicrosoft,
    docsLink: "https://huggingface.co/intfloat",
    embeddingModels: [
      {
        modelName: "intfloat/e5-base-v2",
        modelDim: 768,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        description:
          "A smaller and faster model than the default. It is around 2x faster than the default model at the cost of lower search quality.",
      },
      {
        modelName: "intfloat/e5-small-v2",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        description:
          "The smallest and fastest version of the E5 line of models. If you're running Onyx on a resource constrained system, then this may be a good choice.",
      },
      {
        modelName: "intfloat/multilingual-e5-base",
        modelDim: 768,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        description:
          "For corpora in other languages besides English, this is the one to choose.",
      },
      {
        modelName: "intfloat/multilingual-e5-small",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        description:
          "For corpora in other languages besides English, as well as being on a resource constrained system, this is the one to choose.",
      },
    ],
  },
];

/**
 * Synthetic provider used by the "Add Custom Model" flow. Not a real provider —
 * its `providerName` never reaches the backend (custom self-hosted models are
 * persisted with `provider_type=null` like other self-hosted models). Exists so
 * the modal can be dispatched through `ProviderCredentialsModal` like every
 * other provider.
 */
export const CUSTOM_PROVIDER: EmbeddingProvider = {
  providerName: EmbeddingProviderName.CUSTOM,
  displayName: "Custom Model",
  icon: SvgHardDrive,
  embeddingModels: [],
};

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
 * self-hosted buckets (`NOMIC`, `MICROSOFT`) and `CUSTOM`.
 */
export function isCloudBased(providerName: EmbeddingProviderName): boolean {
  return CLOUD_BASED_PROVIDERS.some((p) => p.providerName === providerName);
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
 *      schema for self-hosted models: Nomic vs Microsoft vs custom must
 *      be inferred from `model_name` by walking a frontend registry.)
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
 * persist (`NOMIC`, `MICROSOFT`, `CUSTOM`).
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
 *      return that bucket's `providerName` (e.g. `NOMIC`, `MICROSOFT`).
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

// ═══════════════════════════════════════════════════════════════════════════
// Image processing
// ═══════════════════════════════════════════════════════════════════════════

export const MAX_IMAGE_SIZE_OPTIONS = ["5", "10", "20", "50", "100"];
