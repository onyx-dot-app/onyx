"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { EmptyMessageCard } from "@opal/components";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import { LLM_GATEWAY_MIN_TIER } from "@/lib/tiers";
import { LLMGatewaySettings } from "@/views/SettingsPage";

export default function LLMGatewayPage() {
  const router = useRouter();
  const gatewayTier = useTierAtLeast(LLM_GATEWAY_MIN_TIER);
  const settings = useSettings();
  const { llmProviders, isLoading, error } = useLLMProviders();
  const hasAccessibleGatewayModel = hasVisibleLLMModel(llmProviders);
  const hasAccess = gatewayTier && hasAccessibleGatewayModel;
  const isLoadingAccess = settings.isLoading || isLoading;

  useEffect(() => {
    if (!isLoadingAccess && !error && !hasAccess) {
      router.replace("/app/settings/general");
    }
  }, [error, hasAccess, isLoadingAccess, router]);

  useEffect(() => {
    if (error) {
      console.error("Failed to load LLM Gateway models", error);
    }
  }, [error]);

  if (error) {
    return (
      <EmptyMessageCard
        sizePreset="main-ui"
        title="Could not load LLM Gateway"
        description="Please refresh the page and try again."
      />
    );
  }

  if (isLoadingAccess || !hasAccess) {
    return null;
  }

  return <LLMGatewaySettings />;
}
