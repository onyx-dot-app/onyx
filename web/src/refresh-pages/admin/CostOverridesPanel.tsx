"use client";

import { ChangeEvent, useMemo, useState } from "react";
import { useSWRConfig } from "swr";
import { toast } from "@/hooks/useToast";
import { ThreeDotsLoader } from "@/components/Loading";
import { ContentAction } from "@opal/layouts";
import { Button, Card, InputTypeIn, MessageCard, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgCheck, SvgEdit, SvgPlus, SvgTrash, SvgX } from "@opal/icons";
import { markdown } from "@opal/utils";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { useAdminLLMProviders } from "@/hooks/useLanguageModels";
import * as GeneralLayouts from "@/layouts/general-layouts";
import {
  CostOverride,
  deleteCostOverride,
  refreshCostOverrides,
  upsertCostOverride,
  useCostOverrides,
} from "@/lib/languageModels/costOverrides";

const RATE_UNIT_LABEL = "USD per 1M tokens";

// Accepts integers/decimals only; "" is allowed mid-edit, validated on submit.
function parseRate(raw: string): number | null {
  if (raw.trim() === "") return null;
  if (!/^\d*\.?\d+$/.test(raw.trim())) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function formatRate(value: number): string {
  return `$${value.toFixed(2)}`;
}

// ============================================================================
// OverrideForm — shared add/edit form (PUT upsert)
// ============================================================================

interface OverrideFormProps {
  // Editing an existing row locks the model name (it's the upsert key).
  existing?: CostOverride;
  onDone: () => void;
}

function OverrideForm({ existing, onDone }: OverrideFormProps) {
  const { mutate } = useSWRConfig();
  const [model, setModel] = useState(existing?.model ?? "");
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

  // Offer the org's configured models as options so the override key matches the
  // model id actually recorded in usage (free-text still allowed for a model not
  // yet configured, e.g. an embedding/rerank id).
  const { llmProviders } = useAdminLLMProviders();
  const modelOptions = useMemo(() => {
    const names = new Set<string>();
    for (const provider of llmProviders ?? []) {
      for (const mc of provider.model_configurations) {
        names.add(mc.name);
      }
    }
    return Array.from(names)
      .sort()
      .map((name) => ({ value: name, label: name }));
  }, [llmProviders]);

  const isEdit = existing !== undefined;
  const parsedInput = parseRate(inputRate);
  const parsedOutput = parseRate(outputRate);
  const canSubmit =
    model.trim() !== "" && parsedInput !== null && parsedOutput !== null;

  async function handleSubmit() {
    if (!canSubmit || parsedInput === null || parsedOutput === null) return;
    setSubmitting(true);
    try {
      await upsertCostOverride({
        model: model.trim(),
        input_cost_per_mtok: parsedInput,
        output_cost_per_mtok: parsedOutput,
        // Empty cache rate => null (cache reads bill at the input rate).
        cache_read_cost_per_mtok: parseRate(cacheRate),
      });
      await refreshCostOverrides(mutate);
      toast.success(`Saved rate for ${model.trim()}.`);
      onDone();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to save override: ${message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card border="solid" rounding="lg">
      <GeneralLayouts.Section
        gap={0.75}
        height="fit"
        alignItems="stretch"
        justifyContent="start"
      >
        <div className="flex flex-col gap-1">
          <Text font="secondary-action" color="text-03">
            Model
          </Text>
          {isEdit ? (
            <InputTypeIn value={model} variant="readOnly" />
          ) : (
            <InputComboBox
              value={model}
              options={modelOptions}
              strict={false}
              placeholder="Select a configured model, or type a model id"
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                setModel(e.target.value)
              }
              onValueChange={(value: string) => setModel(value)}
            />
          )}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="flex flex-col gap-1">
            <Text font="secondary-action" color="text-03">
              {`Input rate (${RATE_UNIT_LABEL})`}
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
              {`Output rate (${RATE_UNIT_LABEL})`}
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
            {`Cache-read rate (${RATE_UNIT_LABEL}, optional)`}
          </Text>
          <InputTypeIn
            value={cacheRate}
            prefixText="$"
            inputMode="decimal"
            placeholder="defaults to input rate"
            onChange={(e: ChangeEvent<HTMLInputElement>) =>
              setCacheRate(e.target.value)
            }
          />
        </div>

        <div className="flex flex-row gap-2 justify-end">
          <Button prominence="tertiary" onClick={onDone} disabled={submitting}>
            Cancel
          </Button>
          <Button
            icon={SvgCheck}
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
          >
            {isEdit ? "Save" : "Add override"}
          </Button>
        </div>
      </GeneralLayouts.Section>
    </Card>
  );
}

// ============================================================================
// OverrideRow — one configured override with edit + delete
// ============================================================================

interface OverrideRowProps {
  override: CostOverride;
}

function OverrideRow({ override }: OverrideRowProps) {
  const { mutate } = useSWRConfig();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteCostOverride(override.model);
      await refreshCostOverrides(mutate);
      toast.success(`Removed override for ${override.model}.`);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to remove override: ${message}`);
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
      <Card border="solid" rounding="lg" padding="sm">
        <div className="flex flex-row items-center justify-between gap-2 p-2">
          <div className="flex flex-col gap-0.5 min-w-0">
            <Text font="main-ui-action" color="text-04" nowrap>
              {override.model}
            </Text>
            <Text font="secondary-body" color="text-03">
              {`In ${formatRate(override.input_cost_per_mtok)} · Out ${formatRate(
                override.output_cost_per_mtok
              )}${
                override.cache_read_cost_per_mtok != null
                  ? ` · Cache ${formatRate(override.cache_read_cost_per_mtok)}`
                  : ""
              } · ${RATE_UNIT_LABEL}`}
            </Text>
            {override.updated_at && (
              <Text font="secondary-body" color="text-02">
                {`Updated ${new Date(override.updated_at).toLocaleString()}`}
              </Text>
            )}
          </div>

          <div className="flex flex-row">
            <Button
              icon={SvgEdit}
              prominence="tertiary"
              aria-label={`Edit override for ${override.model}`}
              disabled={deleting}
              onClick={() => setEditing(true)}
            />
            <Hoverable.Item group="OverrideRow" variant="appear-on-hover">
              <Button
                icon={SvgTrash}
                prominence="tertiary"
                aria-label={`Delete override for ${override.model}`}
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

// ============================================================================
// CostOverridesPanel — section embedded on the Language Models page
// ============================================================================

export default function CostOverridesPanel() {
  const { costOverrides, isLoading, error } = useCostOverrides();
  const [adding, setAdding] = useState(false);

  return (
    <GeneralLayouts.Section
      gap={0.75}
      height="fit"
      alignItems="stretch"
      justifyContent="start"
    >
      <ContentAction
        title="Cost Overrides"
        description={markdown(
          `Set negotiated per-model rates in **${RATE_UNIT_LABEL}**. These override the built-in price book for usage cost calculations.`
        )}
        sizePreset="main-content"
        variant="section"
        rightChildren={
          <Button
            icon={SvgPlus}
            prominence="secondary"
            disabled={adding}
            onClick={() => setAdding(true)}
          >
            Add override
          </Button>
        }
      />

      {adding && <OverrideForm onDone={() => setAdding(false)} />}

      {error ? (
        <MessageCard
          variant="error"
          icon={SvgX}
          title="Failed to load cost overrides."
        />
      ) : isLoading ? (
        <ThreeDotsLoader />
      ) : costOverrides && costOverrides.length > 0 ? (
        <div className="flex flex-col gap-2">
          {costOverrides.map((override) => (
            <OverrideRow key={override.model} override={override} />
          ))}
        </div>
      ) : (
        !adding && (
          <MessageCard
            variant="info"
            title="No cost overrides set."
            description={`Add one to apply a negotiated rate (${RATE_UNIT_LABEL}) for a model.`}
          />
        )
      )}
    </GeneralLayouts.Section>
  );
}
