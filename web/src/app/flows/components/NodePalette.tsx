"use client";

import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { visualFor } from "@/app/flows/components/nodeVisuals";
import type { FlowNodeKind } from "@/app/flows/types";

// Roughly most-reached-for first, so the common ones do not end up on a
// second row when the pane is narrow.
const KINDS: readonly FlowNodeKind[] = [
  "HTTP",
  "AI",
  "CODE",
  "TRANSFORM",
  "CONDITION",
  "SWITCH",
  "SPLIT",
  "FILTER",
  "LOOP",
  "PARALLEL",
  "MERGE",
  "DELAY",
  "SCHEDULE",
  "RETRY",
  "WEBHOOK",
  "HUMAN",
];

export interface NodePaletteProps {
  /** The node a new one is wired after, or null to add it unconnected. */
  afterNodeId: string | null;
  onAdd: (kind: FlowNodeKind) => void;
}

/**
 * Every node kind, as one row of buttons.
 *
 * A palette rather than a drag source: nodes are placed by the layout, so
 * there is nowhere meaningful to drop one. Adding wires the new node after
 * whatever is selected, which is what people mean by "and then".
 */
export function NodePalette({ afterNodeId, onAdd }: NodePaletteProps) {
  const t = useTranslations("flows.palette");

  return (
    <div className="flex flex-row items-center gap-2 flex-wrap">
      <Text font="figure-small-label" color="text-03">
        {afterNodeId === null ? t("addStandalone") : t("addAfterSelected")}
      </Text>
      {KINDS.map((kind) => (
        <Button
          key={kind}
          variant="default"
          prominence="secondary"
          size="sm"
          icon={visualFor(kind).icon}
          onClick={() => onAdd(kind)}
        >
          {t(`kind.${kind}`)}
        </Button>
      ))}
    </div>
  );
}
