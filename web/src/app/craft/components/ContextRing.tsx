"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { ProgressRing, Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";

interface ContextRingProps {
  usedTokens: number;
  contextLimit: number | null;
}

// CRIT ≈ where opencode auto-compacts (context window minus output headroom).
const WARN = 0.7;
const CRIT = 0.9;

const SIZE = 16;

export default function ContextRing({
  usedTokens,
  contextLimit,
}: ContextRingProps) {
  const t = useTranslations("craft.inputBar.contextRing");
  const view = useMemo(() => {
    if (!contextLimit || contextLimit <= 0 || usedTokens <= 0) return null;
    const ratio = usedTokens / contextLimit;
    const pct = Math.min(ratio, 1);
    const displayPct = Math.min(Math.round(ratio * 100), 999);
    const level = pct >= CRIT ? "crit" : pct >= WARN ? "warn" : "ok";
    return { pct, displayPct, level };
  }, [usedTokens, contextLimit]);

  if (!view) return null;

  const color =
    view.level === "crit"
      ? "error"
      : view.level === "warn"
        ? "warning"
        : "neutral";

  const tooltip = t("tooltip", { percent: view.displayPct });

  return (
    <Tooltip tooltip={tooltip} side="top" align="end">
      <Section
        flexDirection="row"
        gap={1.5}
        width="fit"
        height="auto"
        className="select-none"
      >
        {/* The ring reports the value; this repeats it for sighted users. */}
        {view.level !== "ok" && (
          <Text
            font="secondary-body"
            color="text-03"
            wordWrap="whitespace-nowrap"
            aria-hidden
          >
            {`${view.displayPct}%`}
          </Text>
        )}
        <ProgressRing
          value={view.pct}
          max={1}
          color={color}
          track="border"
          size={SIZE}
          aria-label={t("label")}
          // The arc stops at 100%; the spoken value keeps the real percent.
          aria-valuetext={tooltip}
        />
      </Section>
    </Tooltip>
  );
}
