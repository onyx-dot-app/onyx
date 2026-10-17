"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Fold, OverflowText, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgChevronDown, SvgExternalLink } from "@opal/icons";
import { LineLoader } from "@opal/loaders";
import { useOpalStrings } from "@opal/strings";
import type { RichStr } from "@opal/types";
import { useHierarchyBreakdown } from "@/lib/connectors/hooks";
import type {
  CCPairHierarchyBreakdown,
  HierarchyBreakdownEntry,
  HierarchyNodeType,
} from "@/lib/connectors/types";

/** The node type groups with rows, in the backend's order. */
export function breakdownGroups(
  data: CCPairHierarchyBreakdown
): [HierarchyNodeType, HierarchyBreakdownEntry[]][] {
  // SAFETY: the backend keys the dict by its own node type enum, which the union mirrors.
  return Object.entries(data.nodes_by_type).filter(
    (group): group is [HierarchyNodeType, HierarchyBreakdownEntry[]] =>
      group[1] !== undefined
  );
}

interface DocCountProps {
  /** The count, or `null` for a configured node that gave no document. */
  count: number | null;
}
/** The figure with its unit, or "Not indexed". */
function DocCount({ count }: DocCountProps) {
  const t = useTranslations("admin.connector.configuration.breakdown");
  const format = useFormatter();
  if (count === null) {
    return (
      <Text font="main-ui-body" color="text-03" wordWrap="whitespace-nowrap">
        {t("notIndexed")}
      </Text>
    );
  }
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="end"
      gap={0.5}
      width="fit"
      height="fit"
    >
      <Text font="main-ui-body" color="text-04">
        {format.number(count)}
      </Text>
      <Text font="secondary-body" color="text-03" wordWrap="whitespace-nowrap">
        {t("docsUnit", { count })}
      </Text>
    </Section>
  );
}

interface BreakdownRowProps {
  children: React.ReactNode;
  docCount: number | null;
}
/** One row: what the documents sit under, and how many there are. */
function BreakdownRow({ children, docCount }: BreakdownRowProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      alignItems="start"
      gap={2}
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
      <DocCount count={docCount} />
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
      <OverflowText
        // A numeric key (a Confluence page ID) reads as an ID.
        font={
          /^\d+$/.test(entry.raw_node_id) ? "main-ui-mono" : "main-ui-action"
        }
        color={entry.doc_count === null ? "text-03" : "text-04"}
      >
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
          {t("displayName", { name: entry.display_name })}
        </OverflowText>
      )}
    </BreakdownRow>
  );
}

interface BreakdownGroupProps {
  title: string | RichStr;
  children: React.ReactNode;
}
/** One node type: its title, a fold toggle, and its rows. */
function BreakdownGroup({ title, children }: BreakdownGroupProps) {
  const strings = useOpalStrings();
  const [open, setOpen] = useState(true);
  const plainTitle = typeof title === "string" ? title : title.raw;
  const label = open
    ? strings.collapsibleFoldSection(plainTitle)
    : strings.collapsibleExpandSection(plainTitle);
  return (
    <Section alignItems="stretch" gap={0} height="fit">
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        gap={2}
        height="fit"
      >
        <Text font="main-ui-action" color="text-03">
          {title}
        </Text>
        <Button
          icon={SvgChevronDown}
          prominence="internal"
          size="xs"
          aria-label={label}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        />
      </Section>
      <Fold open={open}>
        {/* The gap to the title lives inside the fold, so a closed group has none. */}
        <Section alignItems="stretch" gap={2} height="fit" className="mt-2">
          {children}
        </Section>
      </Fold>
    </Section>
  );
}

interface BreakdownNoteProps {
  children: string;
}
/** A line in place of the list: an error, or nothing to list yet. */
function BreakdownNote({ children }: BreakdownNoteProps) {
  return (
    <Text font="secondary-body" color="text-03">
      {children}
    </Text>
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
  const { data, error } = useHierarchyBreakdown(ccPairId);
  if (error !== undefined) {
    return <BreakdownNote>{t("loadError")}</BreakdownNote>;
  }
  if (data === undefined) return <LineLoader lines={2} />;
  // null until the pair has a successful index run.
  if (data === null) return note("unavailable");
  const groups = breakdownGroups(data);
  if (groups.length === 0 && data.other_doc_count === 0) return note("empty");

  return (
    <Section alignItems="stretch" gap={4} height="fit">
      {groups.map(([nodeType, entries]) => (
        <BreakdownGroup
          key={nodeType}
          title={t(`types.${nodeType}`, { count: entries.length })}
        >
          {entries.map((entry) => (
            <NodeRow key={entry.raw_node_id} entry={entry} />
          ))}
        </BreakdownGroup>
      ))}
      {data.other_doc_count > 0 && (
        <BreakdownRow docCount={data.other_doc_count}>
          <Text font="main-ui-action" color="text-03">
            {t("other")}
          </Text>
        </BreakdownRow>
      )}
    </Section>
  );
}
