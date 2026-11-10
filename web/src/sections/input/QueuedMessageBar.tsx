"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { Text, Button } from "@opal/components";
import { SvgTrash, SvgEdit } from "@opal/icons";
import { cn, clickOnKeyDown } from "@opal/utils";
import { QueuedMessage } from "@/app/app/types";

interface QueuedMessageBarProps {
  messages: readonly QueuedMessage[];
  highlightedIndex: number | null;
  onDiscard: (index: number) => void;
  onHighlight: (index: number | null) => void;
  onEdit?: (index: number) => void;
  disabled?: boolean;
  canEdit?: boolean;
}

function QueuedMessageBar({
  messages,
  highlightedIndex,
  onDiscard,
  onHighlight,
  onEdit,
  disabled = false,
  canEdit = true,
}: QueuedMessageBarProps) {
  const t = useTranslations("chat.input");
  const isEmpty = messages.length === 0;
  const highlightedItemRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    highlightedItemRef.current?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }, [highlightedIndex]);

  return (
    <div
      className={cn(
        "transition-all duration-150",
        isEmpty
          ? "opacity-0 h-0 overflow-hidden"
          : "opacity-100 max-h-[min(16rem,30dvh)] overflow-y-auto overscroll-contain"
      )}
    >
      {!isEmpty && (
        <div className="flex flex-col gap-1 pb-1.5">
          {messages.map((item, index) => {
            const isHighlighted = highlightedIndex === index;

            return (
              <div
                key={item.id}
                ref={isHighlighted ? highlightedItemRef : undefined}
                data-testid="queued-message-bar"
                className={cn(
                  "bg-background-neutral-02 rounded-12 border px-3 py-1.5 flex items-center gap-2 cursor-pointer",
                  isHighlighted ? "border-border-03" : "border-border-01"
                )}
                role="button"
                tabIndex={0}
                aria-label={t("queuedMessageBar.item.ariaLabel")}
                onKeyDown={clickOnKeyDown(() =>
                  onHighlight(isHighlighted ? null : index)
                )}
                onClick={() => onHighlight(isHighlighted ? null : index)}
              >
                <div
                  className="flex-1 min-w-0 overflow-hidden whitespace-nowrap"
                  style={{
                    maskImage:
                      "linear-gradient(to right, black 80%, transparent 100%)",
                    WebkitMaskImage:
                      "linear-gradient(to right, black 80%, transparent 100%)",
                  }}
                >
                  <Text font="secondary-body" color="text-03">
                    {item.text}
                  </Text>
                </div>
                {isHighlighted && (
                  <div className="shrink-0 whitespace-nowrap flex items-center gap-0.5">
                    <span className="translate-y-[1.5px] text-text-02 text-[0.7rem]">
                      ↵
                    </span>
                    <Text font="secondary-body" color="text-02">
                      {t("queuedMessageBar.editHint.label")}
                    </Text>
                    <span className="translate-y-[1.5px] text-text-02 text-[0.7rem]">
                      ⌫
                    </span>
                    <Text font="secondary-body" color="text-02">
                      {t("queuedMessageBar.removeHint.label")}
                    </Text>
                  </div>
                )}
                {onEdit && (
                  <Button
                    icon={SvgEdit}
                    prominence="tertiary"
                    size="xs"
                    disabled={disabled || !canEdit}
                    tooltip={t(
                      canEdit
                        ? "queuedMessageBar.editButton.tooltip"
                        : "queuedMessageBar.editButton.clearDraftTooltip"
                    )}
                    onClick={(event) => {
                      event.stopPropagation();
                      onEdit(index);
                    }}
                  />
                )}
                <Button
                  disabled={disabled}
                  icon={SvgTrash}
                  prominence="tertiary"
                  size="xs"
                  tooltip={t("queuedMessageBar.discardButton.tooltip")}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDiscard(index);
                  }}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default QueuedMessageBar;
