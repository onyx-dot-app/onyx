"use client";

import { usePendingAction } from "@opal/hooks";
import { useTranslations } from "next-intl";
import { useLifecycleBadge } from "@/lib/badges/components";
import { Button, MessageCard, OnyxLoader } from "@opal/components";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { useDecisionModel } from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { saveDecisionModel } from "@/lib/languageModels/svc";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import type { DefaultModel, ModelCapability } from "@/lib/languageModels/types";

// The row's label targets the select by id: the Clear button comes first,
// so an implicit label would forward a title click to it.
const SELECT_ID = "decision-model-select";
const DECISION_CAPABILITIES: readonly ModelCapability[] = ["decision"];

export default function DecisionModelSetting() {
  const t = useTranslations("admin.decisionModels");
  const betaTag = useLifecycleBadge("beta");
  const { model, providers, error, refetch } = useDecisionModel();
  const settings = useSettings();
  const selectedId =
    providers
      ?.find((provider) => provider.id === model?.provider_id)
      ?.model_configurations.find((config) => config.name === model?.model_name)
      ?.id ?? null;

  // One pending save for the Clear button and the select: either disables
  // both until it settles.
  const saving = usePendingAction(async (selection: DefaultModel | null) => {
    try {
      await saveDecisionModel(selection);
      await refetch();
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t("decisionModel.saveFailed")
      );
    }
  });

  return (
    <InputHorizontal
      title={t("decisionModel.title")}
      description={t("decisionModel.description")}
      tag={betaTag}
      suffix="optional"
      withLabel={SELECT_ID}
      fillInput
    >
      {error ? (
        <MessageCard
          variant="error"
          title={t("loadFailed")}
          rightChildren={
            <Button prominence="secondary" onClick={() => void refetch()}>
              {t("retry")}
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
          justifyContent="start"
          alignItems="start"
          height="auto"
          gap={2}
        >
          {model && (
            <Button
              prominence="tertiary"
              size="sm"
              disabled={saving.isPending}
              onClick={() => void saving.run(null)}
            >
              {t("decisionModel.clear")}
            </Button>
          )}
          <SimpleModelSelector
            id={SELECT_ID}
            capabilities={DECISION_CAPABILITIES}
            providers={providers}
            value={selectedId}
            placeholder={t("decisionModel.notConfigured")}
            disabled={saving.isPending}
            grouped={!settings.hide_provider_grouping}
            onChange={(id) => {
              const provider = findProviderOwningModelConfig(providers, id);
              const selected = provider?.model_configurations.find(
                (config) => config.id === id
              );
              if (!provider || !selected) {
                toast.error(t("decisionModel.saveFailed"));
                return;
              }
              return saving.run({
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
