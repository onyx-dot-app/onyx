"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import { NODE_HEIGHT, NODE_WIDTH } from "@/app/flows/graphLayout";
import {
  isDimmedByRun,
  runStatusRingClassName,
  visualFor,
} from "@/app/flows/components/nodeVisuals";
import type { FlowNode, FlowNodeRunStatus } from "@/app/flows/types";

export interface FlowNodeCardProps {
  node: FlowNode;
  x: number;
  y: number;
  selected: boolean;
  /** False when nothing in the graph leads here from the start node. */
  reachable: boolean;
  /** True for the spec's entry node. */
  isStart: boolean;
  /** Set in the run inspector; null while editing. */
  runStatus: FlowNodeRunStatus | null;
  onSelect: (nodeId: string) => void;
}

/**
 * One node on the canvas.
 *
 * A div rather than a Button: the card carries a heading, a subtitle and a
 * couple of badges, which is more than a button should hold. It takes the
 * keyboard handling a button would have given it, the same way `LineItem`
 * does for its rows.
 */
export function FlowNodeCard({
  node,
  x,
  y,
  selected,
  reachable,
  isStart,
  runStatus,
  onSelect,
}: FlowNodeCardProps) {
  const t = useTranslations("flows.canvas");
  const visual = visualFor(node.kind);
  const Icon = visual.icon;

  const border =
    runStatus !== null
      ? runStatusRingClassName(runStatus)
      : selected
        ? visual.accentBorderClassName
        : "border-border-01";

  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      data-flow-node={node.id}
      data-testid={`flow-node-${node.id}`}
      onClick={() => onSelect(node.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(node.id);
        }
      }}
      // Positioned by the layout, so the canvas owns geometry and the card
      // owns appearance.
      style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }}
      className={cn(
        "absolute flex flex-col justify-center gap-1 px-3 rounded-12 border-2",
        "bg-background-neutral-00 cursor-pointer transition-colors",
        "hover:border-border-02 focus-visible:outline-2 focus-visible:outline-action-selection-05",
        border,
        selected && "shadow-lg",
        isDimmedByRun(runStatus) && "opacity-60",
        !reachable && runStatus === null && "border-dashed"
      )}
    >
      <div className="flex flex-row items-center gap-2 min-w-0">
        <span
          className={cn(
            "flex items-center justify-center w-6 h-6 rounded-08 shrink-0",
            visual.chipClassName
          )}
        >
          <Icon size={14} className={visual.iconClassName} />
        </span>
        <div className="min-w-0 truncate">
          <Text
            font="main-ui-action"
            color="text-05"
            wordWrap="whitespace-nowrap"
          >
            {node.name}
          </Text>
        </div>
      </div>

      <div className="flex flex-row items-center gap-1.5 ps-8">
        <Text font="figure-small-label" color="text-03">
          {t(`kind.${node.kind}`)}
        </Text>
        {isStart ? (
          <Text font="figure-small-label" color="text-03">
            {t("startBadge")}
          </Text>
        ) : null}
        {node.for_each !== null ? (
          <Text font="figure-small-label" color="text-03">
            {/* A paced step makes a run slower on purpose; saying so on the
                card answers "why is this taking so long" without a click. */}
            {(node.pause_seconds ?? 0) > 0
              ? t("pacedFanOutBadge", { seconds: node.pause_seconds ?? 0 })
              : t("fanOutBadge")}
          </Text>
        ) : null}
        {!reachable && runStatus === null ? (
          <Text font="figure-small-label" color="text-03">
            {t("unreachableBadge")}
          </Text>
        ) : null}
      </div>
    </div>
  );
}
