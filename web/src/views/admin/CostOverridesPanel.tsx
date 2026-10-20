"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { ContentAction, InputHorizontal, toast } from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import {
  BasicModalFooter,
  Button,
  Card,
  InputCurrency,
  InputTypeIn,
  MessageCard,
  Modal,
  Text,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgEdit, SvgPlus, SvgTrash, SvgWallet, SvgX } from "@opal/icons";
import { markdown } from "@opal/utils";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { getProvider } from "@/lib/languageModels/utils";
import { useProviderNames } from "@/lib/languageModels/useProviderNames";
import {
  filterModelConfigurations,
  findLlmOptionById,
} from "@/lib/languageModels/options";
import { useAdminLanguageModels } from "@/lib/languageModels/hooks";
import { useSettings } from "@/lib/settings/hooks";
import * as GeneralLayouts from "@/layouts/general-layouts";
import {
  deleteCostOverride,
  refreshCostOverrides,
  upsertCostOverride,
  useCostOverrides,
} from "@/lib/languageModels/costOverrides";
import type { CostOverride } from "@/lib/languageModels/types";

/**
 * The label and resolver are passed in: this function cannot call hooks.
 * `providerNames` is `useProviderNames()`.
 */
function getProviderDisplayName(
  provider: string,
  allProvidersLabel: string,
  providerNames: ReturnType<typeof useProviderNames>
): string {
  return provider
    ? providerNames(getProvider(provider)).companyName
    : allProvidersLabel;
}

// Negotiated rates go well below a cent per 1M tokens.
const RATE_PRECISION = 6;

function formatRate(value: number, locale: string): string {
  return `$${value.toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 20,
  })}`;
}

// Shared add/edit modal for the idempotent upsert. Mount it only while open,
// so each open starts from fresh form state.

interface OverrideModalProps {
  // Editing an existing row locks the model name (it's the upsert key).
  existing?: CostOverride;
  onClose: () => void;
}

function OverrideModal({ existing, onClose }: OverrideModalProps) {
  const t = useTranslations("admin.costOverrides");
  const providerNames = useProviderNames();
  const { mutate } = useSWRConfig();
  const { llmProviders, modelPaging } = useAdminLanguageModels();
  const { hide_provider_grouping: hideProviderGrouping } = useSettings();
  const [model, setModel] = useState(existing?.model ?? "");
  const [provider, setProvider] = useState(existing?.provider ?? "");
  const [inputRate, setInputRate] = useState<number | null>(
    existing?.input_cost_per_mtok ?? null
  );
  const [outputRate, setOutputRate] = useState<number | null>(
    existing?.output_cost_per_mtok ?? null
  );
  // Empty (null) bills cache reads at the input rate.
  const [cacheRate, setCacheRate] = useState<number | null>(
    existing?.cache_read_cost_per_mtok ?? null
  );
  const [submitting, setSubmitting] = useState(false);

  // The override keys on the model name; track the picked config id too so the
  // selector can highlight the current choice.
  const [modelConfigId, setModelConfigId] = useState<number | null>(null);

  const isEdit = existing !== undefined;
  const modelLabel = model
    ? `${getProviderDisplayName(provider, t("allProviders.label"), providerNames)} · ${model}`
    : "";
  const canSubmit =
    model.trim() !== "" && inputRate !== null && outputRate !== null;

  async function handleSubmit() {
    if (!canSubmit || inputRate === null || outputRate === null) return;
    setSubmitting(true);
    try {
      await upsertCostOverride({
        model: model.trim(),
        provider,
        input_cost_per_mtok: inputRate,
        output_cost_per_mtok: outputRate,
        cache_read_cost_per_mtok: cacheRate,
      });
      await refreshCostOverrides(mutate);
      toast.success(t("toasts.saved", { model: model.trim() }));
      onClose();
    } catch (e) {
      console.error("Failed to save cost override", e);
      const message = e instanceof Error ? e.message : t("toasts.unknownError");
      toast.error(t("toasts.saveFailed", { message }));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgWallet}
          title={isEdit ? t("form.editTitle") : t("form.newTitle")}
          description={t("form.description")}
          onClose={onClose}
        />
        <Modal.Body alignItems="stretch">
          <InputHorizontal
            withLabel
            title={t("form.model.label")}
            description={t("form.model.description")}
            fillInput
            center
          >
            {isEdit ? (
              <InputTypeIn value={modelLabel} variant="readOnly" />
            ) : (
              <SimpleModelSelector
                nullable
                providers={filterModelConfigurations(llmProviders ?? [], {
                  visibleOnly: false,
                })}
                value={modelConfigId}
                grouped={!hideProviderGrouping}
                modelPaging={modelPaging}
                onChange={(modelConfigurationId) => {
                  const opt = findLlmOptionById(
                    llmProviders,
                    modelConfigurationId
                  );
                  setModel(opt?.modelName ?? "");
                  setProvider(opt?.provider ?? "");
                  setModelConfigId(modelConfigurationId);
                }}
              />
            )}
          </InputHorizontal>

          <InputHorizontal
            withLabel
            title={t("form.inputRate.label")}
            description={t("form.units.description")}
            fillInput
            center
          >
            <InputCurrency
              value={inputRate}
              onChange={setInputRate}
              precision={RATE_PRECISION}
            />
          </InputHorizontal>

          <InputHorizontal
            withLabel
            title={t("form.outputRate.label")}
            description={t("form.units.description")}
            fillInput
            center
          >
            <InputCurrency
              value={outputRate}
              onChange={setOutputRate}
              precision={RATE_PRECISION}
            />
          </InputHorizontal>

          <InputHorizontal
            withLabel
            title={t("form.cacheRate.label")}
            description={t("form.cacheRate.description")}
            suffix="optional"
            fillInput
            center
          >
            <InputCurrency
              value={cacheRate}
              onChange={setCacheRate}
              precision={RATE_PRECISION}
            />
          </InputHorizontal>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button
                prominence="secondary"
                onClick={onClose}
                disabled={submitting}
              >
                {t("form.cancelButton.label")}
              </Button>
            }
            submit={
              <Button
                onClick={handleSubmit}
                disabled={!canSubmit || submitting}
              >
                {isEdit
                  ? t("form.saveButton.label")
                  : t("form.addButton.label")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

// One configured override with edit and delete actions.

interface OverrideRowProps {
  override: CostOverride;
}

function OverrideRow({ override }: OverrideRowProps) {
  const t = useTranslations("admin.costOverrides");
  const providerNames = useProviderNames();
  const locale = useLocale();
  const { mutate } = useSWRConfig();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const providerDisplayName = getProviderDisplayName(
    override.provider,
    t("allProviders.label"),
    providerNames
  );
  const rates = {
    provider: providerDisplayName,
    input: formatRate(override.input_cost_per_mtok, locale),
    output: formatRate(override.output_cost_per_mtok, locale),
  };

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteCostOverride(override.model, override.provider);
      await refreshCostOverrides(mutate);
      toast.success(t("toasts.removed", { model: override.model }));
    } catch (e) {
      console.error("Failed to remove cost override", e);
      const message = e instanceof Error ? e.message : t("toasts.unknownError");
      toast.error(t("toasts.removeFailed", { message }));
      setDeleting(false);
    }
  }

  return (
    <>
      {editing && (
        <OverrideModal existing={override} onClose={() => setEditing(false)} />
      )}
      <Hoverable.Root group="OverrideRow">
        <Card border="solid" rounding={4} padding={2}>
          <div className="flex flex-row items-center justify-between gap-2 p-2">
            <div className="flex flex-col gap-0.5 min-w-0">
              <Text
                font="main-ui-action"
                color="text-04"
                wordWrap="whitespace-nowrap"
              >
                {override.model}
              </Text>
              <Text font="secondary-body" color="text-03">
                {override.cache_read_cost_per_mtok != null
                  ? t("row.ratesWithCache", {
                      ...rates,
                      cache: formatRate(
                        override.cache_read_cost_per_mtok,
                        locale
                      ),
                    })
                  : t("row.rates", rates)}
              </Text>
              {override.updated_at && (
                <Text font="secondary-body" color="text-02">
                  {t("row.updated", {
                    time: new Date(override.updated_at).toLocaleString(locale),
                  })}
                </Text>
              )}
            </div>

            <div className="flex flex-row">
              <Button
                icon={SvgEdit}
                prominence="tertiary"
                aria-label={t("row.editButton.ariaLabel", {
                  provider: providerDisplayName,
                  model: override.model,
                })}
                disabled={deleting}
                onClick={() => setEditing(true)}
              />
              <Hoverable.Item group="OverrideRow" variant="appear-on-hover">
                <Button
                  icon={SvgTrash}
                  prominence="tertiary"
                  aria-label={t("row.deleteButton.ariaLabel", {
                    provider: providerDisplayName,
                    model: override.model,
                  })}
                  disabled={deleting}
                  onClick={handleDelete}
                />
              </Hoverable.Item>
            </div>
          </div>
        </Card>
      </Hoverable.Root>
    </>
  );
}

// Section embedded on the Language Models page.

export default function CostOverridesPanel() {
  const t = useTranslations("admin.costOverrides");
  const { costOverrides, isLoading, error } = useCostOverrides();
  const [adding, setAdding] = useState(false);

  return (
    <GeneralLayouts.Section
      gap={3}
      height="fit"
      alignItems="stretch"
      justifyContent="start"
    >
      <ContentAction
        title={t("panel.title")}
        description={markdown(t("panel.description"))}
        sizePreset="main-content"
        variant="section"
        rightChildren={
          <Button
            icon={SvgPlus}
            prominence="secondary"
            onClick={() => setAdding(true)}
          >
            {t("panel.addButton.label")}
          </Button>
        }
      />

      {adding && <OverrideModal onClose={() => setAdding(false)} />}

      {error ? (
        <MessageCard
          variant="error"
          icon={SvgX}
          title={t("panel.error.title")}
        />
      ) : isLoading ? (
        <PageLoader />
      ) : costOverrides && costOverrides.length > 0 ? (
        <div className="flex flex-col gap-2">
          {costOverrides.map((override) => (
            <OverrideRow
              key={`${override.provider}:${override.model}`}
              override={override}
            />
          ))}
        </div>
      ) : (
        <MessageCard
          variant="info"
          title={t("empty.title")}
          description={t("empty.description")}
        />
      )}
    </GeneralLayouts.Section>
  );
}
