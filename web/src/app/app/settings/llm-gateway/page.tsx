"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { Tier } from "@/lib/settings/types";
import { LLMGatewaySettings } from "@/views/SettingsPage";

export default function LLMGatewayPage() {
  const router = useRouter();
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);
  const { llmProviders } = useLLMProviders();
  const hasAccessibleGatewayModel =
    llmProviders?.some((provider) =>
      provider.model_configurations.some((model) => model.is_visible)
    ) ?? false;
  const hasAccess = enterpriseTier && hasAccessibleGatewayModel;

  useEffect(() => {
    if (llmProviders && !hasAccess) {
      router.replace("/app/settings/general");
    }
  }, [hasAccess, llmProviders, router]);

  if (!hasAccess) {
    return null;
  }

  return <LLMGatewaySettings />;
}
