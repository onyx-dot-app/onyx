import type { IconFunctionComponent } from "@opal/types";
import { SvgCpu } from "@opal/icons";
import {
  SvgOpenai,
  SvgAzure,
  SvgGoogle,
  SvgLitellm,
  SvgCohere,
  SvgNomic,
  SvgVoyage,
} from "@opal/logos";

// ─── Embedding provider names ────────────────────────────────────────────────

export enum EmbeddingProviderName {
  OPENAI = "openai",
  COHERE = "cohere",
  VOYAGE = "voyage",
  GOOGLE = "google",
  LITELLM = "litellm",
  AZURE = "azure",
}

// ─── Embedding provider registry ─────────────────────────────────────────────

export interface EmbeddingProviderEntry {
  icon: IconFunctionComponent;
  displayName: string;
}

const PROVIDERS: Record<string, EmbeddingProviderEntry> = {
  [EmbeddingProviderName.OPENAI]: {
    icon: SvgOpenai,
    displayName: "OpenAI",
  },
  [EmbeddingProviderName.COHERE]: {
    icon: SvgCohere,
    displayName: "Cohere",
  },
  [EmbeddingProviderName.VOYAGE]: {
    icon: SvgVoyage,
    displayName: "Voyage AI",
  },
  [EmbeddingProviderName.GOOGLE]: {
    icon: SvgGoogle,
    displayName: "Google",
  },
  [EmbeddingProviderName.LITELLM]: {
    icon: SvgLitellm,
    displayName: "LiteLLM",
  },
  [EmbeddingProviderName.AZURE]: {
    icon: SvgAzure,
    displayName: "Azure",
  },
};

const DEFAULT_ENTRY: EmbeddingProviderEntry = {
  icon: SvgCpu,
  displayName: "Self-hosted",
};

// Self-hosted models (provider_type is null) get a dedicated entry.
const SELF_HOSTED_ENTRY: EmbeddingProviderEntry = {
  icon: SvgNomic,
  displayName: "Self-hosted",
};

export function getEmbeddingProvider(
  providerType: string | null
): EmbeddingProviderEntry {
  if (!providerType) return SELF_HOSTED_ENTRY;
  return (
    PROVIDERS[providerType] ?? {
      ...DEFAULT_ENTRY,
      displayName: providerType.charAt(0).toUpperCase() + providerType.slice(1),
    }
  );
}
