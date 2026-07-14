"use client";

import { useMemo, useState } from "react";
import { SvgCpu } from "@opal/icons";
import { Divider, Switch, Text } from "@opal/components";
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
 * supported provider configured. Mirrors the model picker's toggle: on shows
 * the recommended build-mode providers, off shows the full catalog. Clicking
 * a card opens the shared provider-specific modal (hosted by
 * BuildOnboardingProvider).
 */
const craftKeys: string[] = CRAFT_PROVIDERS.map(({ key }) => key);

export default function CraftLlmSetup() {
  const { openProviderModal } = useOnboarding();
  const { llmProviderOptions } = useLLMProviderOptions();
  const [recommendedOnly, setRecommendedOnly] = useState(true);

  // Recommended = the build-mode providers; the full catalog keeps them
  // first, then the remaining well-known providers.
  const providerKeys = useMemo(() => {
    if (recommendedOnly) return craftKeys;
    const others = (llmProviderOptions ?? [])
      .map((option) => option.name)
      .filter((name) => !isSupportedProviderType(name));
    return [...craftKeys, ...others];
  }, [recommendedOnly, llmProviderOptions]);

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
        rightChildren={
          <div className="flex items-center gap-2">
            <Text font="secondary-body" color="text-03" nowrap>
              Recommended providers only
            </Text>
            <Switch
              checked={recommendedOnly}
              onCheckedChange={setRecommendedOnly}
            />
          </div>
        }
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
