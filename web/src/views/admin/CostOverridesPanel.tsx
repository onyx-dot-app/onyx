"use client";

import { ChangeEvent, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { ContentAction, PageLoader, toast } from "@opal/layouts";
import {
  Button,
  Card,
  InputTypeIn,
  MessageCard,
  OpenButton,
  Text,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgCheck, SvgEdit, SvgPlus, SvgTrash, SvgX } from "@opal/icons";
import { markdown } from "@opal/utils";
import ModelSelector from "@/sections/model-selector/ModelSelector";
import { getProvider } from "@/lib/languageModels";
import { LLMOption } from "@/lib/languageModels/options";
import { useAdminLLMProviders } from "@/lib/languageModels/hooks";
import * as GeneralLayouts from "@/layouts/general-layouts";
import {
  CostOverride,
  deleteCostOverride,
  refreshCostOverrides,
  upsertCostOverride,
  useCostOverrides,
} from "@/lib/languageModels/costOverrides";

/** `allProvidersLabel` is passed in: this module cannot call translation hooks. */
function getProviderDisplayName(
  provider: string,
  allProvidersLabel: string
): string {
  return provider ? getProvider(provider).companyName : allProvidersLabel;
}

// Accepts integers/decimals only; "" is allowed mid-edit, validated on submit.
function parseRate(raw: string): number | null {
  if (raw.trim() === "") return null;
  if (!/^\d*\.?\d+$/.test(raw.trim())) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function formatRate(value: number, locale: string): string {
  return `$${value.toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 20,
  })}`;
}

// Shared add/edit form for the idempotent upsert.

interface OverrideFormProps {
  // Editing an existing row locks the model name (it's the upsert key).
  existing?: CostOverride;
  onDone: () => void;
}

function OverrideForm({ existing, onDone }: OverrideFormProps) {
  const t = useTranslations("admin.costOverrides");
  const { mutate } = useSWRConfig();
  const { llmProviders } = useAdminLLMProviders();
  const [model, setModel] = useState(existing?.model ?? "");
  const [provider, setProvider] = useState(existing?.provider ?? "");
  const [inputRate, setInputRate] = useState(
    existing ? String(existing.input_cost_per_mtok) : ""
  );
  const [outputRate, setOutputRate] = useState(
    existing ? String(existing.output_cost_per_mtok) : ""
  );
  const [cacheRate, setCacheRate] = useState(
    existing?.cache_read_cost_per_mtok != null
      ? String(existing.cache_read_cost_per_mtok)
      : ""
  );
  const [submitting, setSubmitting] = useState(false);

  // The override keys on the model name; track the picked config id too so the
  // selector can highlight the current choice.
  const [modelConfigId, setModelConfigId] = useState<number | null>(null);

  const isEdit = existing !== undefined;
  const parsedInput = parseRate(inputRate);
  const parsedOutput = parseRate(outputRate);
  // Empty cache rate is valid (bill cache reads at the input rate); a non-empty
  // but unparseable value must block submit, not silently drop to null.
  const parsedCache = parseRate(cacheRate);
  const cacheValid = cacheRate.trim() === "" || parsedCache !== null;
  const modelLabel = model
    ? `${getProviderDisplayName(provider, t("allProviders.label"))} · ${model}`
    : "";
  const canSubmit =
    model.trim() !== "" &&
    parsedInput !== null &&
    parsedOutput !== null &&
    cacheValid;

  async function handleSubmit() {
    if (!canSubmit || parsedInput === null || parsedOutput === null) return;
    setSubmitting(true);
    try {
      await upsertCostOverride({
        model: model.trim(),
        provider,
        input_cost_per_mtok: parsedInput,
        output_cost_per_mtok: parsedOutput,
        // Empty cache rate => null (cache reads bill at the input rate).
        cache_read_cost_per_mtok: parsedCache,
      });
      await refreshCostOverrides(mutate);
      toast.success(t("toasts.saved", { model: model.trim() }));
      onDone();
    } catch (e) {
      console.error("Failed to save cost override", e);
      const message = e instanceof Error ? e.message : t("toasts.unknownError");
      toast.error(t("toasts.saveFailed", { message }));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card border="solid" rounding={4}>
      <GeneralLayouts.Section
        gap={3}
        height="fit"
        alignItems="stretch"
        justifyContent="start"
      >
        <div className="flex flex-col gap-1">
          <Text font="secondary-action" color="text-03">
            {t("form.model.label")}
          </Text>
          {isEdit ? (
            <InputTypeIn value={modelLabel} variant="readOnly" />
          ) : (
            <ModelSelector
              value={modelConfigId}
              providerOptions={llmProviders ?? []}
              includeHiddenModels
              onChange={(opt: LLMOption) => {
                setModel(opt.modelName);
                setProvider(opt.provider);
                setModelConfigId(opt.modelConfigurationId ?? null);
              }}
              renderTrigger={() => (
                <OpenButton>
                  {modelLabel || t("form.model.placeholder")}
                </OpenButton>
              )}
              side="bottom"
            />
          )}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="flex flex-col gap-1">
            <Text font="secondary-action" color="text-03">
              {t("form.inputRate.label")}
            </Text>
            <InputTypeIn
              value={inputRate}
              prefixText="$"
              inputMode="decimal"
              placeholder="3.00"
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                setInputRate(e.target.value)
              }
            />
          </div>
          <div className="flex flex-col gap-1">
            <Text font="secondary-action" color="text-03">
              {t("form.outputRate.label")}
            </Text>
            <InputTypeIn
              value={outputRate}
              prefixText="$"
              inputMode="decimal"
              placeholder="15.00"
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                setOutputRate(e.target.value)
              }
            />
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Text font="secondary-action" color="text-03">
            {t("form.cacheRate.label")}
          </Text>
          <InputTypeIn
            value={cacheRate}
            prefixText="$"
            inputMode="decimal"
            placeholder={t("form.cacheRate.placeholder")}
            onChange={(e: ChangeEvent<HTMLInputElement>) =>
              setCacheRate(e.target.value)
            }
          />
        </div>

        <div className="flex flex-row gap-2 justify-end">
          <Button prominence="tertiary" onClick={onDone} disabled={submitting}>
            {t("form.cancelButton.label")}
          </Button>
          <Button
            icon={SvgCheck}
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
          >
            {isEdit ? t("form.saveButton.label") : t("form.addButton.label")}
          </Button>
        </div>
      </GeneralLayouts.Section>
    </Card>
  );
}

// One configured override with edit and delete actions.

interface OverrideRowProps {
  override: CostOverride;
}

function OverrideRow({ override }: OverrideRowProps) {
  const t = useTranslations("admin.costOverrides");
  const locale = useLocale();
  const { mutate } = useSWRConfig();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const providerDisplayName = getProviderDisplayName(
    override.provider,
    t("allProviders.label")
  );

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

  if (editing) {
    return (
      <OverrideForm existing={override} onDone={() => setEditing(false)} />
    );
  }

  return (
    <Hoverable.Root group="OverrideRow">
      <Card border="solid" rounding={4} padding={2}>
        <div className="flex flex-row items-center justify-between gap-2 p-2">
          <div className="flex flex-col gap-0.5 min-w-0">
            <Text font="main-ui-action" color="text-04" nowrap>
              {override.model}
            </Text>
            <Text font="secondary-body" color="text-03">
              {override.cache_read_cost_per_mtok != null
                ? t("row.ratesWithCache", {
                    provider: providerDisplayName,
                    input: formatRate(override.input_cost_per_mtok, locale),
                    output: formatRate(override.output_cost_per_mtok, locale),
                    cache: formatRate(
                      override.cache_read_cost_per_mtok,
                      locale
                    ),
                  })
                : t("row.rates", {
                    provider: providerDisplayName,
                    input: formatRate(override.input_cost_per_mtok, locale),
                    output: formatRate(override.output_cost_per_mtok, locale),
                  })}
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
            disabled={adding}
            onClick={() => setAdding(true)}
          >
            {t("panel.addButton.label")}
          </Button>
        }
      />

      {adding && <OverrideForm onDone={() => setAdding(false)} />}

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
        !adding && (
          <MessageCard
            variant="info"
            title={t("empty.title")}
            description={t("empty.description")}
          />
        )
      )}
    </GeneralLayouts.Section>
  );
}
