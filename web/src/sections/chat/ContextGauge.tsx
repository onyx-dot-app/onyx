"use client";

import { Tooltip } from "@opal/components";
import ContextRing, { ContextRingTone } from "@/refresh-components/ContextRing";
import { ContextUsage } from "@/sections/chat/interfaces";

interface ContextGaugeProps {
  usage: ContextUsage | null;
}

function tone(pct: number): ContextRingTone {
  if (pct >= 0.9) return "critical";
  if (pct >= 0.7) return "warning";
  return "normal";
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

  // Pass a plain string so Opal's Tooltip wraps it in <Text color="inherit"> —
  // i.e. the readable inverted color for the dark tooltip surface. Passing a
  // custom <Content> here applied light-background text colors (unreadable).
  const tooltip = `${formatTokens(usage.used_tokens)} / ${formatTokens(
    usage.max_input_tokens,
  )} (${pctLabel}%) — older messages are trimmed to fit when the window is full.`;

  return (
    <Tooltip tooltip={tooltip} side="top">
      <ContextRing
        fraction={pct}
        tone={tone(pct)}
        ariaLabel={`Context window ${pctLabel}% used`}
      />
    </Tooltip>
  );
}

export default ContextGauge;
