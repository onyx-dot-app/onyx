"use client";

import { useLocale, useTranslations } from "next-intl";
import { Card, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import ColumnLabels from "@/views/admin/ServiceStatusPage/ColumnLabels";
import type {
  ClusterIndexStatus,
  VectorQuantization,
} from "@/lib/service-status/types";
import { useClusterStatus } from "@/lib/service-status/hooks";
import { compactParts } from "@/views/admin/ServiceStatusPage/format";
import ValueWithUnit from "@/views/admin/ServiceStatusPage/ValueWithUnit";

// The Index Settings labels for each quantization.
const QUANTIZATION_LABEL_KEYS = {
  scalar_7_bit: "vectorQuantization.scalar7Bit.label",
  scalar_1_bit: "vectorQuantization.scalar1Bit.label",
} as const;

function deletedPercent(index: ClusterIndexStatus): number {
  const total = index.chunk_count + index.deleted_chunk_count;
  return total > 0 ? Math.round((100 * index.deleted_chunk_count) / total) : 0;
}

interface IndexRowsProps {
  indexes: ClusterIndexStatus[];
}

function IndexRows({ indexes }: IndexRowsProps) {
  const t = useTranslations("admin.serviceStatus.indexes");
  const tCluster = useTranslations("admin.serviceStatus.cluster");
  const tIndexSettings = useTranslations("admin.indexSettings");
  const locale = useLocale();
  const currentChunks =
    indexes.find((index) => index.is_current)?.chunk_count ?? 0;

  function detail(index: ClusterIndexStatus): string {
    const quantization: VectorQuantization = index.vector_quantization;
    if (quantization === "none") {
      return t("detail", { dim: index.model_dim });
    }
    return t("detailQuantized", {
      dim: index.model_dim,
      quantization: tIndexSettings(QUANTIZATION_LABEL_KEYS[quantization]),
    });
  }

  return (
    <Section gap={3} alignItems="stretch" width="full">
      <ColumnLabels title={t("title")} labels={[t("chunks"), t("shards")]} />
      <Section gap={2} alignItems="stretch" width="full">
        {indexes.map((index) => (
          <Card
            key={index.index_name}
            border="solid"
            rounding={4}
            padding={3}
            data-testid="service-status-index"
          >
            <Section
              flexDirection="row"
              gap={2}
              alignItems="start"
              width="full"
            >
              {/* min-w-0: a long model name truncates instead of widening the column. */}
              <Section
                gap={0.25}
                alignItems="start"
                width="full"
                className="min-w-0"
              >
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={0.5}
                  alignItems="center"
                  width="full"
                  className="min-w-0"
                >
                  {/* One line; the full ID, with its organization prefix, is in the tooltip. */}
                  <Text
                    as="p"
                    font="main-ui-action"
                    color="text-04"
                    maxLines={1}
                    tooltip={index.model_name}
                  >
                    {index.model_name.split("/").pop() ?? index.model_name}
                  </Text>
                  {!index.is_current && <Tag title={t("reindex")} />}
                </Section>
                <Text as="p" font="secondary-body" color="text-03">
                  {detail(index)}
                </Text>
              </Section>
              <Section gap={0.25} alignItems="start" width="full">
                <ValueWithUnit
                  size="row"
                  value={compactParts(index.chunk_count, locale)[0]}
                  unit={compactParts(index.chunk_count, locale)[1]}
                />
                {/* A reindex copies the current index, so its share of the
                  current chunks is how far it has got. */}
                {!index.is_current && currentChunks > 0 && (
                  <Text as="p" font="secondary-body" color="text-03">
                    {t("reindexProgress", {
                      percent: Math.min(
                        100,
                        Math.round((100 * index.chunk_count) / currentChunks)
                      ),
                    })}
                  </Text>
                )}
                {index.is_current && index.deleted_chunk_count > 0 && (
                  <Text as="p" font="secondary-body" color="text-03">
                    {t("deleted", { percent: deletedPercent(index) })}
                  </Text>
                )}
              </Section>
              <Section gap={0.25} alignItems="start" width="full">
                <ValueWithUnit
                  size="row"
                  value={tCluster("shardLayout", {
                    primaries: index.primary_shards,
                    copies: index.replicas + 1,
                  })}
                  unit={tCluster("copies")}
                />
              </Section>
            </Section>
          </Card>
        ))}
      </Section>
    </Section>
  );
}

export default function IndexesList() {
  const { data } = useClusterStatus();
  // The page shows the loader until the first read.
  return data ? <IndexRows indexes={data.indexes} /> : null;
}
