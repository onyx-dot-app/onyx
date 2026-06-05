"use client";

import { Text, Tooltip } from "@opal/components";
import { ContextUsage } from "@/sections/chat/interfaces";

interface ContextGaugeProps {
  usage: ContextUsage | null;
}

// Track + fill colors come from the Opal CSS-var palette (see web/CLAUDE.md
// §Colors) so dark mode and theming are handled automatically.
const TRACK_COLOR = "var(--background-neutral-03)";

function fillColor(pct: number): string {
  if (pct >= 0.9) return "var(--status-error-05)";
  if (pct >= 0.7) return "var(--status-warning-05)";
  return "var(--theme-primary-05)";
}

// 12_400 -> "12.4k". Sub-1k values keep their digits ("840").
function formatTokens(n: number): string {
  if (n < 1000) return `${Math.round(n)}`;
  return `${(n / 1000).toFixed(1)}k`;
}

/**
 * A small ring gauge showing how much of the chat's context window is used.
 * Returns null when there's no usable ratio (no data or non-positive max).
 */
function ContextGauge({ usage }: ContextGaugeProps) {
  if (usage == null || usage.max_input_tokens <= 0) return null;

  const pct = Math.min(1, usage.used_tokens / usage.max_input_tokens);
  const pctLabel = Math.round(pct * 100);
  const color = fillColor(pct);

  const tooltip = (
    <div className="flex flex-col gap-1">
      <Text font="secondary-body" color="inherit" as="p">
        {`${formatTokens(usage.used_tokens)} / ${formatTokens(
          usage.max_input_tokens
        )} (${pctLabel}%)`}
      </Text>
      <Text font="secondary-body" color="inherit" as="p">
        Older messages are trimmed to fit when the window is full.
      </Text>
    </div>
  );

  return (
    <Tooltip tooltip={tooltip} side="top">
      <div
        role="img"
        aria-label={`Context window ${pctLabel}% used`}
        className="size-4 shrink-0 rounded-full"
        style={{
          background: `conic-gradient(${color} ${pct * 360}deg, ${TRACK_COLOR} 0deg)`,
        }}
      />
    </Tooltip>
  );
}

export default ContextGauge;
