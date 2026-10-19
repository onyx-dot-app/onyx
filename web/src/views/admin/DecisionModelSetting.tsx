"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, MessageCard, OnyxLoader } from "@opal/components";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { useDecisionModel } from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { saveDecisionModel } from "@/lib/languageModels/svc";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import type { DefaultModel } from "@/lib/languageModels/types";

export default function DecisionModelSetting() {
  const t = useTranslations("admin.chatPreferences");
  const { model, providers, error, refetch } = useDecisionModel();
  const settings = useSettings();
  const [pending, setPending] = useState(false);
  const selectedId =
    providers
      ?.find((provider) => provider.id === model?.provider_id)
      ?.model_configurations.find((config) => config.name === model?.model_name)
      ?.id ?? null;

  async function save(selection: DefaultModel | null) {
    if (pending) return;
    setPending(true);
    try {
      await saveDecisionModel(selection);
      await refetch();
      toast.success(t("decisionModel.saved"));
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t("decisionModel.saveFailed")
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <InputHorizontal
      title={t("decisionModel.title")}
      description={t("decisionModel.description")}
      suffix="optional"
    >
      {error ? (
        <MessageCard
          variant="error"
          title={t("taskModels.loadFailed")}
          rightChildren={
            <Button prominence="secondary" onClick={() => void refetch()}>
              {t("taskModels.retry.label")}
            </Button>
          }
        />
      ) : !providers ? (
        <OnyxLoader size={24} />
      ) : (
        <Section
          role="group"
          aria-label={t("decisionModel.title")}
          flexDirection="row"
          width="fit"
          height="auto"
          gap={2}
        >
          {model && (
            <Button
              prominence="tertiary"
              size="sm"
              disabled={pending}
              onClick={() => void save(null)}
            >
              {t("decisionModel.clear")}
            </Button>
          )}
          <SimpleModelSelector
            includeDecisionOnly
            providers={providers}
            value={selectedId}
            placeholder={t("decisionModel.notConfigured")}
            disabled={pending}
            grouped={!settings.hide_provider_grouping}
            onChange={(id) => {
              const provider = findProviderOwningModelConfig(providers, id);
              const selected = provider?.model_configurations.find(
                (config) => config.id === id
              );
              if (!provider || !selected) {
                toast.error(t("toasts.providerResolveFailed"));
                return;
              }
              void save({
                provider_id: provider.id,
                model_name: selected.name,
              });
            }}
          />
        </Section>
      )}
    </InputHorizontal>
  );
}
