"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { Text, Button } from "@opal/components";
import { SvgTrash, SvgEdit, SvgArrowUp } from "@opal/icons";
import { cn } from "@opal/utils";
import { QueuedMessage } from "@/app/app/types";
import type { PendingChatMessage } from "@/lib/chat/types";

interface QueuedMessageBarProps {
  /** Craft's local queue or the chat's server-owned pending messages. */
  messages: readonly (QueuedMessage | PendingChatMessage)[];
  highlightedId: (QueuedMessage | PendingChatMessage)["id"] | null;
  onDiscard: (index: number) => void;
  onEdit?: (index: number) => void;
  onSendNow?: (index: number) => void;
  disabled?: boolean;
  canEdit?: boolean;
}

function QueuedMessageBar({
  messages,
  highlightedId,
  onDiscard,
  onEdit,
  onSendNow,
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
  }, [highlightedId]);

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
        // Rows are not focusable: the composer's arrow keys move the highlight,
        // and Tab reaches each row's buttons.
        <div role="list" className="flex flex-col gap-1 pb-1.5">
          {messages.map((item, index) => {
            const isHighlighted = highlightedId === item.id;
            const text = "text" in item ? item.text : item.message;

            return (
              <div
                key={item.id}
                ref={isHighlighted ? highlightedItemRef : undefined}
                data-testid="queued-message-bar"
                className={cn(
                  "bg-background-neutral-02 rounded-12 border px-3 py-1.5 flex items-center gap-2",
                  isHighlighted ? "border-border-03" : "border-border-01"
                )}
                role="listitem"
                aria-current={isHighlighted || undefined}
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
                    {text}
                  </Text>
                </div>
                {isHighlighted && (
                  <div className="shrink-0 whitespace-nowrap flex items-center gap-0.5">
                    <span className="translate-y-[1.5px] text-text-02 text-[0.7rem]">
                      ↵
                    </span>
                    <Text font="secondary-body" color="text-02">
                      {t(
                        onSendNow
                          ? "queuedMessageBar.sendHint.label"
                          : "queuedMessageBar.editHint.label"
                      )}
                    </Text>
                    <span className="translate-y-[1.5px] text-text-02 text-[0.7rem]">
                      ⌫
                    </span>
                    <Text font="secondary-body" color="text-02">
                      {t("queuedMessageBar.removeHint.label")}
                    </Text>
                  </div>
                )}
                {onSendNow && (
                  <Button
                    icon={SvgArrowUp}
                    prominence="tertiary"
                    size="xs"
                    disabled={disabled}
                    aria-label={t("queuedMessageBar.sendButton.ariaLabel", {
                      message: text,
                    })}
                    tooltip={t("queuedMessageBar.sendButton.tooltip")}
                    onClick={() => onSendNow(index)}
                  />
                )}
                {onEdit && (
                  <Button
                    icon={SvgEdit}
                    aria-label={t("queuedMessageBar.editButton.ariaLabel", {
                      message: text,
                    })}
                    prominence="tertiary"
                    size="xs"
                    disabled={disabled || !canEdit}
                    tooltip={t(
                      canEdit
                        ? "queuedMessageBar.editButton.tooltip"
                        : "queuedMessageBar.editButton.clearDraftTooltip"
                    )}
                    onClick={() => onEdit(index)}
                  />
                )}
                <Button
                  disabled={disabled}
                  icon={SvgTrash}
                  aria-label={t("queuedMessageBar.discardButton.ariaLabel", {
                    message: text,
                  })}
                  prominence="tertiary"
                  size="xs"
                  tooltip={t("queuedMessageBar.discardButton.tooltip")}
                  onClick={() => onDiscard(index)}
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
