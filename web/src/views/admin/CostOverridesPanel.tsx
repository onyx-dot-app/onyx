"use client";

import { useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  ConfirmationModalLayout,
  ContentAction,
  InputHorizontal,
  Section,
  toast,
} from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import {
  BasicModalFooter,
  Button,
  InputCurrency,
  InputTypeIn,
  MessageCard,
  Modal,
  SelectCard,
  Text,
  useCreateModal,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgPlus, SvgSettings, SvgTrash, SvgWallet, SvgX } from "@opal/icons";
import { escapeMarkdown, markdown } from "@opal/utils";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { getModelIcon, getProvider } from "@/lib/languageModels/utils";
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

// Rates are entered to the cent per 1M tokens.
const RATE_PRECISION = 2;

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
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void handleSubmit();
          }}
        >
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
                <Button type="submit" disabled={!canSubmit || submitting}>
                  {isEdit
                    ? t("form.saveButton.label")
                    : t("form.addButton.label")}
                </Button>
              }
            />
          </Modal.Footer>
        </form>
      </Modal.Content>
    </Modal>
  );
}

// One configured override, styled like the provider cards above it: the card
// opens the edit modal, and delete asks for confirmation first.

interface OverrideRowProps {
  override: CostOverride;
}

function OverrideRow({ override }: OverrideRowProps) {
  const t = useTranslations("admin.costOverrides");
  const providerNames = useProviderNames();
  const locale = useLocale();
  const format = useFormatter();
  const { mutate } = useSWRConfig();
  const [editing, setEditing] = useState(false);
  const deleteModal = useCreateModal();
  const providerDisplayName = getProviderDisplayName(
    override.provider,
    t("allProviders.label"),
    providerNames
  );
  const rateParts = [
    t("row.input", { value: formatRate(override.input_cost_per_mtok, locale) }),
    t("row.output", {
      value: formatRate(override.output_cost_per_mtok, locale),
    }),
    ...(override.cache_read_cost_per_mtok != null
      ? [
          t("row.cache", {
            value: formatRate(override.cache_read_cost_per_mtok, locale),
          }),
        ]
      : []),
  ];
  const description = override.updated_at
    ? t("row.description", {
        provider: providerDisplayName,
        time: format.dateTime(new Date(override.updated_at), {
          dateStyle: "medium",
        }),
      })
    : providerDisplayName;
  const ariaNames = {
    provider: providerDisplayName,
    model: override.model,
  };

  async function handleDelete() {
    try {
      await deleteCostOverride(override.model, override.provider);
      await refreshCostOverrides(mutate);
      deleteModal.toggle(false);
      toast.success(t("toasts.removed", { model: override.model }));
    } catch (e) {
      console.error("Failed to remove cost override", e);
      const message = e instanceof Error ? e.message : t("toasts.unknownError");
      toast.error(t("toasts.removeFailed", { message }));
    }
  }

  return (
    <>
      {editing && (
        <OverrideModal existing={override} onClose={() => setEditing(false)} />
      )}

      {deleteModal.isOpen && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={markdown(
            t("deleteModal.title", { model: escapeMarkdown(override.model) })
          )}
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button variant="danger" onClick={handleDelete}>
              {t("deleteModal.submit.label")}
            </Button>
          }
        >
          <Text font="main-ui-body" color="text-03">
            {markdown(
              t("deleteModal.description", {
                model: escapeMarkdown(override.model),
                provider: escapeMarkdown(providerDisplayName),
              })
            )}
          </Text>
        </ConfirmationModalLayout>
      )}

      <Hoverable.Root
        group="OverrideRow"
        interaction={deleteModal.isOpen ? "hover" : "rest"}
      >
        <SelectCard
          state="filled"
          padding={2}
          rounding={4}
          aria-label={override.model}
          onClick={() => setEditing(true)}
        >
          <Section gap={0} alignItems="stretch" height="fit">
            <ContentAction
              icon={getModelIcon(override.provider, override.model)}
              title={override.model}
              description={description}
              titleMaxLines={1}
              descriptionMaxLines={1}
              sizePreset="main-ui"
              variant="section"
              padding={2}
              rightChildren={
                <div className="flex flex-row">
                  <Hoverable.Item group="OverrideRow" variant="appear-on-hover">
                    <Button
                      icon={SvgTrash}
                      prominence="tertiary"
                      aria-label={t("row.deleteButton.ariaLabel", ariaNames)}
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteModal.toggle(true);
                      }}
                    />
                  </Hoverable.Item>
                  <Button
                    icon={SvgSettings}
                    prominence="tertiary"
                    aria-label={t("row.editButton.ariaLabel", ariaNames)}
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditing(true);
                    }}
                  />
                </div>
              }
            />
            {/* Lines up under the description: ContentAction padding (0.5rem) plus
                the main-ui description indent (1.375rem). */}
            <div className="ps-[1.875rem] pb-2">
              <Section
                flexDirection="row"
                justifyContent="start"
                alignItems="center"
                width="fit"
                height="fit"
                gap={3}
              >
                {rateParts.map((part) => (
                  <Text key={part} font="secondary-mono" color="text-03">
                    {part}
                  </Text>
                ))}
              </Section>
            </div>
          </Section>
        </SelectCard>
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
