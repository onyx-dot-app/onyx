"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Divider, OverflowText, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgExternalLink } from "@opal/icons";
import { LineLoader } from "@opal/loaders";
import type {
  CCPairHierarchyBreakdown,
  HierarchyBreakdownEntry,
  HierarchyNodeType,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

interface BreakdownRowProps {
  children: React.ReactNode;
  /** The count, or `null` for a configured node that gave no document. */
  docCount: number | null;
}
/** One row: what the documents sit under, and how many there are. */
function BreakdownRow({ children, docCount }: BreakdownRowProps) {
  const t = useTranslations("admin.connector.configuration.breakdown");
  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      gap={2}
      padding={1}
      height="fit"
    >
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        gap={1}
        height="fit"
        className="min-w-0 flex-1"
      >
        {children}
      </Section>
      <Text
        font="secondary-body"
        color={docCount === null ? "text-03" : "text-04"}
        wordWrap="whitespace-nowrap"
      >
        {docCount === null ? t("notIndexed") : t("docs", { count: docCount })}
      </Text>
    </Section>
  );
}

interface NodeRowProps {
  entry: HierarchyBreakdownEntry;
}
/** One node: its key, a link to it, and its name. */
function NodeRow({ entry }: NodeRowProps) {
  const t = useTranslations("admin.connector.configuration.breakdown");
  return (
    <BreakdownRow docCount={entry.doc_count}>
      {/* A SharePoint key is a whole site URL, so the key truncates and the link rides on an icon. */}
      <OverflowText font="secondary-body" color="text-04">
        {entry.raw_node_id}
      </OverflowText>
      {entry.link !== null && (
        <Button
          icon={SvgExternalLink}
          prominence="tertiary"
          size="xs"
          href={entry.link}
          target="_blank"
          aria-label={t("open")}
          tooltip={t("open")}
        />
      )}
      {entry.display_name !== null && (
        <OverflowText font="secondary-body" color="text-03">
          {entry.display_name}
        </OverflowText>
      )}
    </BreakdownRow>
  );
}

interface BreakdownNoteProps {
  children: string;
}
/** A line in place of the list: an error, or nothing to list yet. */
function BreakdownNote({ children }: BreakdownNoteProps) {
  return (
    <Section padding={2} height="fit">
      <Text font="secondary-body" color="text-03">
        {children}
      </Text>
    </Section>
  );
}

export interface HierarchyBreakdownProps {
  ccPairId: number;
  /** Nothing else fills the section, so an empty breakdown says so. */
  showEmpty?: boolean;
}

/** The pair's documents by hierarchy node, one foldable group per node type. */
export default function HierarchyBreakdown({
  ccPairId,
  showEmpty = false,
}: HierarchyBreakdownProps) {
  const t = useTranslations("admin.connector.configuration.breakdown");
  const note = (key: "empty" | "unavailable") =>
    showEmpty ? <BreakdownNote>{t(key)}</BreakdownNote> : null;
  // The request reads every document of the pair, so it runs once per visit and gives up early.
  const { data, error } = useSWR<CCPairHierarchyBreakdown | null>(
    SWR_KEYS.ccPairHierarchyBreakdown(ccPairId),
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      errorRetryCount: 1,
    }
  );
  if (error !== undefined) {
    return <BreakdownNote>{t("loadError")}</BreakdownNote>;
  }
  if (data === undefined) {
    return (
      <Section padding={2} height="fit">
        <LineLoader lines={2} />
      </Section>
    );
  }
  // null until the pair has a successful index run.
  if (data === null) return note("unavailable");
  // SAFETY: the backend keys the dict by its own node type enum, which the union mirrors.
  const groups = Object.entries(data.nodes_by_type).filter(
    (group): group is [HierarchyNodeType, HierarchyBreakdownEntry[]] =>
      group[1] !== undefined
  );
  if (groups.length === 0 && data.other_doc_count === 0) return note("empty");

  return (
    <Section alignItems="stretch" gap={1} padding={1} height="fit">
      {groups.map(([nodeType, entries]) => (
        <Divider
          key={nodeType}
          title={t(`types.${nodeType}`, { count: entries.length })}
          foldable
          defaultOpen
        >
          <Section alignItems="stretch" gap={0} height="fit">
            {entries.map((entry) => (
              <NodeRow key={entry.raw_node_id} entry={entry} />
            ))}
          </Section>
        </Divider>
      ))}
      {data.other_doc_count > 0 && (
        <BreakdownRow docCount={data.other_doc_count}>
          <Text font="secondary-body" color="text-03">
            {t("other")}
          </Text>
        </BreakdownRow>
      )}
    </Section>
  );
}
