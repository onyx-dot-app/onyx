"use client";

import { getProvider } from "@/lib/languageModels";
import { LLMProviderFormProps } from "@/lib/languageModels/types";

interface ProviderSetupModalProps extends Omit<
  LLMProviderFormProps,
  "variant" | "existingLlmProvider"
> {
  /**
   * Well-known provider type to set up; null renders nothing. Unknown keys
   * resolve to the custom-provider modal.
   */
  providerKey: string | null;
}

/**
 * Hosts the provider-specific setup modal (onboarding variant) for a provider
 * key. Single shared entry point for onboarding surfaces (main app LLM step,
 * craft welcome page) so they don't each re-implement modal resolution.
 */
export default function ProviderSetupModal({
  providerKey,
  ...formProps
}: ProviderSetupModalProps) {
  if (!providerKey) return null;

  const { Modal } = getProvider(providerKey);
  return <Modal variant="onboarding" {...formProps} />;
}
