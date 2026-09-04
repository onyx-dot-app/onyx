"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Card,
  InputSelect,
  MessageCard,
  Table,
  Text,
  createTableColumns,
} from "@opal/components";
import { SvgCpu, SvgX } from "@opal/icons";
import { PageLoader, Section } from "@opal/layouts";
import { formatCalendarDay } from "@/lib/dateUtils";
import type { DateRange } from "@/refresh-components/DateRangePicker";
import {
  type SystemUsageCategory,
  useSystemUsage,
} from "@/lib/usage/systemUsage";
import type { UsageExportTotals } from "@/lib/usage/userUsage";
import { formatCost, formatTokens } from "@/lib/utils";

const ALL_FILTER = "__all__";
const UNATTRIBUTED_CATEGORY = "unattributed";
const IMAGE_SUMMARIZATION_FLOW = "image_summarization";
const CONTEXTUAL_RAG_DOC_SUMMARY_FLOW = "contextual_rag_doc_summary";
const CONTEXTUAL_RAG_CHUNK_CONTEXT_FLOW = "contextual_rag_chunk_context";
const KG_DOCUMENT_CLASSIFICATION_FLOW = "kg_document_classification";
const KG_DEEP_EXTRACTION_FLOW = "kg_deep_extraction";

interface SystemUsageRow extends UsageExportTotals {
  category: string;
  total_tokens: number;
}

type SystemUsageTranslate = ReturnType<
  typeof useTranslations<"admin.systemUsage">
>;

function emptyTotals(): UsageExportTotals {
  return {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cost_cents: 0,
  };
}

function categoryLabel(category: string, t: SystemUsageTranslate): string {
  switch (category) {
    case IMAGE_SUMMARIZATION_FLOW:
      return t("categories.imageSummarization.label");
    case CONTEXTUAL_RAG_DOC_SUMMARY_FLOW:
      return t("categories.contextualRagDocumentSummary.label");
    case CONTEXTUAL_RAG_CHUNK_CONTEXT_FLOW:
      return t("categories.contextualRagChunkContext.label");
    case KG_DOCUMENT_CLASSIFICATION_FLOW:
      return t("categories.kgDocumentClassification.label");
    case KG_DEEP_EXTRACTION_FLOW:
      return t("categories.kgDeepExtraction.label");
    case UNATTRIBUTED_CATEGORY:
      return t("categories.unattributed.label");
    default:
      return category;
  }
}

function filterCategory(
  category: SystemUsageCategory,
  model: string,
  provider: string
): SystemUsageRow | null {
  const records = category.records.filter(
    (record) =>
      (model === ALL_FILTER || record.model === model) &&
      (provider === ALL_FILTER || record.provider === provider)
  );
  if (records.length === 0) return null;

  const totals = records.reduce(
    (sum, record) => ({
      input_tokens: sum.input_tokens + record.input_tokens,
      output_tokens: sum.output_tokens + record.output_tokens,
      cache_read_tokens: sum.cache_read_tokens + record.cache_read_tokens,
      cache_creation_tokens:
        sum.cache_creation_tokens + record.cache_creation_tokens,
      cost_cents: sum.cost_cents + record.cost_cents,
    }),
    emptyTotals()
  );
  return {
    category: category.category,
    ...totals,
    total_tokens: totals.input_tokens + totals.output_tokens,
  };
}

const tc = createTableColumns<SystemUsageRow>();

function buildColumns(t: SystemUsageTranslate) {
  return [
    tc.qualifier({ content: "icon", getContent: () => SvgCpu }),
    tc.column("category", {
      header: t("table.columns.category.header"),
      weight: 40,
      cell: (value) => (
        <Text font="main-ui-body" color="text-05">
          {categoryLabel(value, t)}
        </Text>
      ),
    }),
    tc.column("cost_cents", {
      header: t("table.columns.spend.header"),
      weight: 18,
      alignment: "right",
      cell: (value) => (
        <Text font="main-ui-action" color="text-05">
          {formatCost(value)}
        </Text>
      ),
    }),
    tc.column("total_tokens", {
      header: t("table.columns.tokens.header"),
      weight: 18,
      alignment: "right",
      cell: (value) => (
        <Text font="main-ui-action" color="text-05">
          {formatTokens(value)}
        </Text>
      ),
    }),
    tc.column("input_tokens", {
      header: t("table.columns.input.header"),
      weight: 12,
      alignment: "right",
      cell: (value) => (
        <Text font="main-ui-body" color="text-03">
          {formatTokens(value)}
        </Text>
      ),
    }),
    tc.column("output_tokens", {
      header: t("table.columns.output.header"),
      weight: 12,
      alignment: "right",
      cell: (value) => (
        <Text font="main-ui-body" color="text-03">
          {formatTokens(value)}
        </Text>
      ),
    }),
  ];
}

interface SystemUsagePanelProps {
  timeRange?: DateRange;
}

export default function SystemUsagePanel({ timeRange }: SystemUsagePanelProps) {
  const t = useTranslations("admin.systemUsage");
  const locale = useLocale();
  const { usage, isLoading, error } = useSystemUsage(timeRange);
  const [model, setModel] = useState(ALL_FILTER);
  const [provider, setProvider] = useState(ALL_FILTER);
  const columns = useMemo(() => buildColumns(t), [t]);
  const records = useMemo(
    () => usage?.categories.flatMap((category) => category.records) ?? [],
    [usage]
  );
  const models = useMemo(
    () => Array.from(new Set(records.map((record) => record.model))).sort(),
    [records]
  );
  const providers = useMemo(
    () =>
      Array.from(
        new Set(records.map((record) => record.provider).filter(Boolean))
      ).sort(),
    [records]
  );
  useEffect(() => {
    if (model !== ALL_FILTER && !models.includes(model)) setModel(ALL_FILTER);
  }, [model, models]);
  useEffect(() => {
    if (provider !== ALL_FILTER && !providers.includes(provider)) {
      setProvider(ALL_FILTER);
    }
  }, [provider, providers]);
  const rows = useMemo(
    () =>
      (usage?.categories ?? []).flatMap((category) => {
        const row = filterCategory(category, model, provider);
        return row ? [row] : [];
      }),
    [usage, model, provider]
  );
  const totalCostCents = rows.reduce((sum, row) => sum + row.cost_cents, 0);
  const totalTokens = rows.reduce((sum, row) => sum + row.total_tokens, 0);
  const unattributedCostCents =
    rows.find((row) => row.category === UNATTRIBUTED_CATEGORY)?.cost_cents ?? 0;

  const header = (
    <Section alignItems="stretch" gap={0.125} height="fit">
      <Text font="heading-h3">{t("panel.title")}</Text>
      <Text font="secondary-body" color="text-03">
        {usage
          ? t("panel.description", {
              start: formatCalendarDay(usage.start, { withYear: true }),
              end: formatCalendarDay(usage.end, { withYear: true }),
            })
          : t("panel.emptyDescription")}
      </Text>
    </Section>
  );

  if (isLoading) {
    return (
      <Section alignItems="stretch" gap={1} height="fit">
        {header}
        <PageLoader />
      </Section>
    );
  }
  if (error) {
    return (
      <Section alignItems="stretch" gap={1} height="fit">
        {header}
        <MessageCard
          variant="error"
          icon={SvgX}
          title={t("panel.error.title")}
        />
      </Section>
    );
  }

  return (
    <Section alignItems="stretch" gap={1} height="fit">
      {header}
      <Card border="solid" rounding={4} padding={3}>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="start"
          wrap
          gap={2}
          height="fit"
        >
          <Section alignItems="start" gap={0.125} width="fit" height="fit">
            <Text font="secondary-body" color="text-03">
              {t("summary.spend.label")}
            </Text>
            <Text font="heading-h3">{formatCost(totalCostCents, locale)}</Text>
          </Section>
          <Section alignItems="start" gap={0.125} width="fit" height="fit">
            <Text font="secondary-body" color="text-03">
              {t("summary.tokens.label")}
            </Text>
            <Text font="heading-h3">{formatTokens(totalTokens, locale)}</Text>
          </Section>
          <Section alignItems="start" gap={0.125} width="fit" height="fit">
            <Text font="secondary-body" color="text-03">
              {t("summary.unattributed.label")}
            </Text>
            <Text font="heading-h3">
              {formatCost(unattributedCostCents, locale)}
            </Text>
          </Section>
        </Section>
      </Card>

      <Section
        flexDirection="row"
        justifyContent="end"
        alignItems="center"
        wrap
        gap={0.5}
        height="fit"
      >
        {models.length > 0 && (
          <Section width={12} height="fit">
            <InputSelect value={model} onValueChange={setModel}>
              <InputSelect.Trigger placeholder={t("filters.allModels.label")} />
              <InputSelect.Content>
                <InputSelect.Item value={ALL_FILTER}>
                  {t("filters.allModels.label")}
                </InputSelect.Item>
                {models.map((option) => (
                  <InputSelect.Item key={option} value={option}>
                    {option}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
          </Section>
        )}
        {providers.length > 0 && (
          <Section width={12} height="fit">
            <InputSelect value={provider} onValueChange={setProvider}>
              <InputSelect.Trigger
                placeholder={t("filters.allProviders.label")}
              />
              <InputSelect.Content>
                <InputSelect.Item value={ALL_FILTER}>
                  {t("filters.allProviders.label")}
                </InputSelect.Item>
                {providers.map((option) => (
                  <InputSelect.Item key={option} value={option}>
                    {option}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
          </Section>
        )}
      </Section>

      <Table
        key={`${model}-${provider}`}
        data={rows}
        columns={columns}
        getRowId={(row) => row.category}
        initialSorting={[{ id: "cost_cents", desc: true }]}
        emptyState={
          <Text font="main-ui-body" color="text-03">
            {t("table.empty.description")}
          </Text>
        }
      />
    </Section>
  );
}
