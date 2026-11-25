"use client";

import React, { useEffect, useMemo, useState } from "react";
import { FileDescriptor } from "@/app/app/types";
import "katex/dist/katex.min.css";
import MessageSwitcher from "@/lib/timeline/chat/message/MessageSwitcher";
import { cn, richNodes } from "@opal/utils";
import useScreenSize from "@/hooks/useScreenSize";
import { Badge, Button, CopyButton, Text } from "@opal/components";
import { SvgChevronDown, SvgChevronUp, SvgEdit, SvgSparkle } from "@opal/icons";
import { Hoverable } from "@opal/core";
import { Section } from "@opal/layouts";
import { useOverflow } from "@opal/hooks";
import FileDisplay from "./FileDisplay";
import MessageTime from "@/lib/timeline/chat/message/MessageTime";
import { placeMentions, MENTION_TRIGGER } from "@/lib/chat/mentions";
import type { ComposedMention, MessageEdit, Mention } from "@/lib/chat/types";
import type { IconFunctionComponent } from "@opal/types";
import { useTranslations } from "next-intl";
import { chatFindTextKey } from "@/lib/chatFind/match";
import { CHAT_FIND_UNFOLD_EVENT } from "@/lib/chatFind/highlights";

// The chip icon of each mention kind.
const MENTION_CHIP_ICONS: Record<Mention["type"], IconFunctionComponent> = {
  skill: SvgSparkle,
};

interface HumanMessageBubbleProps {
  content: string;
  // What the question mentioned; each `@name` shows as a chip.
  mentions?: ComposedMention[];
  /** Marks the text for find in chat (`chatFindTextKey`). */
  findKey?: string;
}

export function HumanMessageBubble({
  content,
  mentions,
  findKey,
}: HumanMessageBubbleProps) {
  const t = useTranslations("chat.messages.humanMessage");
  const [textElement, setTextElement] = useState<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const clipped = useOverflow(textElement);
  useEffect(() => {
    if (!textElement) return;
    const unfold = () => setExpanded(true);
    textElement.addEventListener(CHAT_FIND_UNFOLD_EVENT, unfold);
    return () =>
      textElement.removeEventListener(CHAT_FIND_UNFOLD_EVENT, unfold);
  }, [textElement]);
  const body = useMemo(() => {
    if (!mentions?.length) return content;
    const parts: React.ReactNode[] = [];
    let textStart = 0;
    for (const mention of placeMentions(content, mentions)) {
      parts.push(
        content.slice(textStart, mention.index),
        <span
          key={mention.index}
          data-testid="mention-chip"
          data-mention-type={mention.type}
          className="inline-block align-middle"
        >
          <Badge
            icon={MENTION_CHIP_ICONS[mention.type]}
            title={`${MENTION_TRIGGER}${mention.name}`}
            color="info"
            size={5}
          />
        </span>
      );
      textStart = mention.index + MENTION_TRIGGER.length + mention.name.length;
    }
    parts.push(content.slice(textStart));
    return richNodes(parts);
  }, [content, mentions]);

  return (
    <div data-testid="human-message-bubble" className="md:max-w-150">
      <div
        className={
          "max-w-120 md:max-w-150 whitespace-break-spaces break-anywhere rounded-t-16 rounded-es-16 bg-background-tint-02 py-2 px-3"
        }
        onCopy={(e) => {
          const selection = window.getSelection();
          if (selection) {
            e.preventDefault();
            const text = selection
              .toString()
              .replace(/\n{2,}/g, "\n")
              .trim();
            e.clipboardData.setData("text/plain", text);
          }
        }}
      >
        <div
          ref={setTextElement}
          data-chat-find-fold={clipped && !expanded ? "closed" : undefined}
          className={cn(
            !expanded && "max-h-72 overflow-hidden",
            clipped &&
              "[mask-image:linear-gradient(to_bottom,black_70%,transparent)]"
          )}
        >
          <div
            className="inline-block align-middle"
            data-chat-find-text={findKey}
          >
            {/* Not a `p`: the chips' badges are blocks. */}
            <Text dir="auto" font="main-content-body" color="text-04">
              {body}
            </Text>
          </div>
        </div>
        {(clipped || expanded) && (
          <Button
            prominence="tertiary"
            size="sm"
            rightIcon={expanded ? SvgChevronUp : SvgChevronDown}
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded
              ? t("foldButton.collapseLabel")
              : t("foldButton.expandLabel")}
          </Button>
        )}
      </div>
    </div>
  );
}

interface HumanMessageProps {
  // Content and display
  content: string;
  files?: FileDescriptor[];
  mentions?: ComposedMention[];
  timeSent?: string;

  // Message navigation - nodeId for tree position, messageId for editing
  nodeId: number;
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;

  /** Starts an edit of this message in the composer. */
  onEdit?: (edit: MessageEdit) => void;

  // Streaming and generation
  stopGenerating?: () => void;
  disableSwitchingForStreaming?: boolean;
}

// Memoization comparison - compare by value for primitives, by reference for objects/arrays
function arePropsEqual(
  prev: HumanMessageProps,
  next: HumanMessageProps
): boolean {
  return (
    prev.content === next.content &&
    prev.nodeId === next.nodeId &&
    prev.messageId === next.messageId &&
    prev.files === next.files &&
    prev.mentions === next.mentions &&
    prev.timeSent === next.timeSent &&
    prev.disableSwitchingForStreaming === next.disableSwitchingForStreaming &&
    prev.otherMessagesCanSwitchTo === next.otherMessagesCanSwitchTo &&
    prev.onEdit === next.onEdit
    // Skip: stopGenerating, onMessageSelection (inline function props)
  );
}

const HumanMessage = React.memo(function HumanMessage({
  content,
  files,
  mentions,
  timeSent,
  nodeId,
  messageId,
  otherMessagesCanSwitchTo,
  onEdit,
  onMessageSelection,
  stopGenerating = () => null,
  disableSwitchingForStreaming = false,
}: HumanMessageProps) {
  const t = useTranslations("chat.messages");

  const { isMobile } = useScreenSize();

  // Use nodeId for switching (finding position in siblings)
  const indexInSiblings = otherMessagesCanSwitchTo?.indexOf(nodeId);
  // indexOf returns -1 if not found, treat that as undefined
  const currentMessageInd =
    indexInSiblings !== undefined && indexInSiblings !== -1
      ? indexInSiblings
      : undefined;

  const getPreviousMessage = () => {
    if (
      currentMessageInd !== undefined &&
      currentMessageInd > 0 &&
      otherMessagesCanSwitchTo
    ) {
      return otherMessagesCanSwitchTo[currentMessageInd - 1];
    }
    return undefined;
  };

  const getNextMessage = () => {
    if (
      currentMessageInd !== undefined &&
      currentMessageInd < (otherMessagesCanSwitchTo?.length || 0) - 1 &&
      otherMessagesCanSwitchTo
    ) {
      return otherMessagesCanSwitchTo[currentMessageInd + 1];
    }
    return undefined;
  };

  const copyEditButtonContent = useMemo(
    () => (
      <Section
        flexDirection="row"
        alignItems="center"
        width="fit"
        height="fit"
        gap={0}
        className="shrink mx-1"
      >
        <CopyButton
          getCopyText={() => content}
          prominence="tertiary"
          data-testid="HumanMessage/copy-button"
        />
        {onEdit && messageId != null && (
          <Button
            icon={SvgEdit}
            prominence="tertiary"
            tooltip={t("humanMessage.editButton.tooltip")}
            onClick={() =>
              onEdit({
                messageId,
                message: content,
                mentions: mentions ?? [],
                files: files ?? [],
              })
            }
            data-testid="HumanMessage/edit-button"
          />
        )}
      </Section>
    ),
    [content, files, mentions, messageId, onEdit, t]
  );

  const copyEditButton = (
    <Hoverable.Item group="humanMessage" variant="appear-on-hover">
      {copyEditButtonContent}
    </Hoverable.Item>
  );

  return (
    <Hoverable.Root group="humanMessage" width="full">
      <div
        id="onyx-human-message"
        className="group/human-message flex flex-col justify-end w-full relative"
      >
        <FileDisplay files={files || []} />
        <div className="flex justify-end">
          {!isMobile && copyEditButton}
          <HumanMessageBubble
            content={content}
            mentions={mentions}
            findKey={chatFindTextKey("user", nodeId)}
          />
        </div>
        <Section
          flexDirection="row"
          justifyContent="end"
          alignItems="center"
          height="fit"
          gap={0}
          className="mt-1"
        >
          {isMobile && copyEditButton}
          {/* The send time sits under the bubble, at its end. */}
          {timeSent && (
            <div className="px-1 opacity-0 transition-opacity duration-150 group-hover/human-message:opacity-100 group-hover/human-message:delay-300 group-focus-within/human-message:opacity-100 no-hover:opacity-100">
              <MessageTime timeSent={timeSent} />
            </div>
          )}
          {currentMessageInd !== undefined &&
            onMessageSelection &&
            otherMessagesCanSwitchTo &&
            otherMessagesCanSwitchTo.length > 1 && (
              <MessageSwitcher
                disableForStreaming={disableSwitchingForStreaming}
                currentPage={currentMessageInd + 1}
                totalPages={otherMessagesCanSwitchTo.length}
                handlePrevious={() => {
                  stopGenerating();
                  const prevMessage = getPreviousMessage();
                  if (prevMessage !== undefined) {
                    onMessageSelection(prevMessage);
                  }
                }}
                handleNext={() => {
                  stopGenerating();
                  const nextMessage = getNextMessage();
                  if (nextMessage !== undefined) {
                    onMessageSelection(nextMessage);
                  }
                }}
              />
            )}
        </Section>
      </div>
    </Hoverable.Root>
  );
}, arePropsEqual);

export default HumanMessage;
