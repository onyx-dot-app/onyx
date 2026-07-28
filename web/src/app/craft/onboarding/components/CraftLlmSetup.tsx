"use client";

import { useMemo } from "react";
import { SvgCpu } from "@opal/icons";
import { Divider } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import LLMProviderCard from "@/sections/onboarding/components/LLMProviderCard";
import { getProvider } from "@/lib/languageModels";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";
import {
  CRAFT_PROVIDERS,
  isSupportedProviderType,
} from "@/app/craft/onboarding/constants";
import { useOnboarding } from "@/app/craft/onboarding/BuildOnboardingProvider";

/**
 * Inline provider setup shown on the craft welcome page when an admin has no
 * provider configured. Craft routes every provider through the Onyx gateway,
 * so the whole catalog is offered; the common providers just sort first.
 * Clicking a card opens the shared provider-specific modal (hosted by
 * BuildOnboardingProvider).
 */
const craftKeys: string[] = CRAFT_PROVIDERS;

export default function CraftLlmSetup() {
  const { openProviderModal } = useOnboarding();
  const { llmProviderOptions } = useLLMProviderOptions();

  const providerKeys = useMemo(() => {
    const others = (llmProviderOptions ?? [])
      .map((option) => option.name)
      .filter((name) => !isSupportedProviderType(name));
    return [...craftKeys, ...others];
  }, [llmProviderOptions]);

  return (
    <div
      className="flex flex-col w-full p-1 rounded-16 border border-border-01 bg-background-tint-00"
      aria-label="craft-llm-setup"
    >
      <ContentAction
        icon={SvgCpu}
        title="Connect a model provider"
        description="Craft agents need a model provider to build."
        sizePreset="main-ui"
        variant="section"
        padding="lg"
      />
      <Divider />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 w-full max-h-56 overflow-y-auto [&>*:last-child:nth-child(odd)]:col-span-full">
        {providerKeys.map((key) => {
          const { productName, companyName } = getProvider(key);
          return (
            <LLMProviderCard
              key={key}
              title={productName}
              subtitle={companyName}
              providerName={key}
              onClick={() => openProviderModal(key)}
            />
          );
        })}
      </div>
    </div>
  );
}
