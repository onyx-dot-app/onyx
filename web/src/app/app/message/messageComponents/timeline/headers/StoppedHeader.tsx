import React from "react";
import { useTranslations } from "next-intl";
import { SvgFold, SvgExpand } from "@opal/icons";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { noProp } from "@/lib/utils";
import { cn, clickOnKeyDown } from "@opal/utils";

export interface StoppedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}

/** Header when user stopped/cancelled */
export const StoppedHeader = React.memo(function StoppedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
}: StoppedHeaderProps) {
  const t = useTranslations("chat.messages.timeline");
  const isInteractive = collapsible && totalSteps > 0;

  const className = cn(
    "flex items-center justify-between w-full rounded-12",
    isInteractive ? "cursor-pointer" : "cursor-default"
  );

  const label = (
    <div className="px-(--timeline-header-text-padding-x) py-(--timeline-header-text-padding-y)">
      <Text as="p" mainUiAction text03>
        {t("interruptedThinking.label")}
      </Text>
    </div>
  );

  if (!isInteractive) {
    return (
      <div className={className} aria-disabled>
        {label}
      </div>
    );
  }

  return (
    // The row holds its own expand button, so it stays a div with button
    // semantics rather than a <button> wrapping a <button>.
    <div
      role="button"
      tabIndex={0}
      aria-label={t("toggleRow.ariaLabel")}
      onKeyDown={clickOnKeyDown(onToggle)}
      onClick={onToggle}
      className={className}
    >
      {label}

      <Button
        prominence="tertiary"
        size="md"
        onClick={noProp(onToggle)}
        rightIcon={isExpanded ? SvgFold : SvgExpand}
        aria-label={
          isExpanded
            ? t("collapseButton.ariaLabel")
            : t("expandButton.ariaLabel")
        }
        aria-expanded={isExpanded}
      >
        {t("stepsButton.label", { count: totalSteps })}
      </Button>
    </div>
  );
});
