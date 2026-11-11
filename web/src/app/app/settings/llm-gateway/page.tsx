"use client";

import { useNavigation } from "@opal/navigation";
import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { EmptyMessageCard } from "@opal/components";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import { LLM_GATEWAY_MIN_TIER } from "@/lib/tiers/utils";
import { LLMGatewaySettings } from "@/views/SettingsPage";

export default function LLMGatewayPage() {
  const t = useTranslations("settings.gateway");
  const navigation = useNavigation();
  const gatewayTier = useTierAtLeast(LLM_GATEWAY_MIN_TIER);
  const settings = useSettings();
  const { llmProviders, isLoading, error } = useLanguageModels();
  const hasAccessibleGatewayModel = hasVisibleLLMModel(llmProviders);
  const hasAccess = gatewayTier && hasAccessibleGatewayModel;
  const isLoadingAccess = settings.isLoading || isLoading;
  const gatewayDisabled =
    !settings.isLoading && settings.llm_gateway_enabled === false;

  useEffect(() => {
    if (!isLoadingAccess && !error && !gatewayDisabled && !hasAccess) {
      navigation.go("/app/settings/general", { replace: true });
    }
  }, [error, gatewayDisabled, hasAccess, isLoadingAccess, navigation]);

  useEffect(() => {
    if (error) {
      console.error("Failed to load LLM Gateway models", error);
    }
  }, [error]);

  if (error) {
    return (
      <EmptyMessageCard
        sizePreset="main-ui"
        title={t("loadError.title")}
        description={t("loadError.description")}
      />
    );
  }

  if (isLoadingAccess) {
    return null;
  }

  if (gatewayDisabled) {
    return (
      <EmptyMessageCard
        sizePreset="main-ui"
        title={t("adminDisabled.title")}
        description={t("adminDisabled.description")}
      />
    );
  }

  if (!hasAccess) {
    return null;
  }

  return <LLMGatewaySettings />;
}
