"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
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
import type {
  ComposedMention,
  ComposedMessage,
  Mention,
} from "@/lib/chat/types";
import type { IconFunctionComponent } from "@opal/types";
import { useTranslations } from "next-intl";
import { chatFindTextKey } from "@/lib/chatFind/match";
import { CHAT_FIND_UNFOLD_EVENT } from "@/lib/chatFind/highlights";

interface MessageEditingProps {
  content: string;
  onSubmitEdit: (editedContent: string) => void;
  onCancelEdit: () => void;
}

function MessageEditing({
  content,
  onSubmitEdit,
  onCancelEdit,
}: MessageEditingProps) {
  const t = useTranslations("chat.messages");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [editedContent, setEditedContent] = useState(content);

  useEffect(() => {
    if (!textareaRef.current) return;

    // Focus the textarea
    textareaRef.current.focus();
    textareaRef.current.select();
  }, []);

  function handleSubmit() {
    onSubmitEdit(editedContent);
  }

  function handleCancel() {
    setEditedContent(content);
    onCancelEdit();
  }

  return (
    <div className="w-full">
      <div
        className={cn(
          "w-full h-full border rounded-16 overflow-hidden p-3 flex flex-col gap-2"
        )}
      >
        <textarea
          ref={textareaRef}
          dir="auto"
          className={cn(
            "w-full h-full resize-none outline-hidden bg-transparent overflow-y-scroll whitespace-normal break-word"
          )}
          value={editedContent}
          style={{ scrollbarWidth: "thin" }}
          onChange={(e) => {
            setEditedContent(e.target.value);
            textareaRef.current!.style.height = "auto";
            e.target.style.height = `${e.target.scrollHeight}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              handleCancel();
            }
            // Submit edit if "Command Enter" is pressed, like in ChatGPT
            if (e.key === "Enter" && e.metaKey) handleSubmit();
          }}
        />
        <div className="flex justify-end gap-1">
          <Button onClick={handleSubmit}>
            {t("messageEditing.submitButton.label")}
          </Button>
          <Button prominence="secondary" onClick={handleCancel}>
            {t("messageEditing.cancelButton.label")}
          </Button>
        </div>
      </div>
    </div>
  );
}

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

  // Editing functionality - takes (edited, messageId) to allow stable callback reference
  onEdit?: (edited: ComposedMessage, messageId: number) => void;

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
  content: initialContent,
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

  // TODO (@raunakab):
  //
  // This is some duplicated state that is patching a memoization issue with `HumanMessage`.
  // Fix this later.
  const [content, setContent] = useState(initialContent);

  const [isEditing, setIsEditing] = useState(false);
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
        {onEdit && (
          <Button
            icon={SvgEdit}
            prominence="tertiary"
            tooltip={t("humanMessage.editButton.tooltip")}
            onClick={() => setIsEditing(true)}
            data-testid="HumanMessage/edit-button"
          />
        )}
      </Section>
    ),
    [content, onEdit, t]
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
        className="flex flex-col justify-end w-full relative"
      >
        <FileDisplay files={files || []} />
        {isEditing ? (
          <MessageEditing
            content={content}
            onSubmitEdit={(editedContent) => {
              // Don't update UI for edits that can't be persisted
              if (messageId === undefined || messageId === null) {
                setIsEditing(false);
                return;
              }
              // The edit has no `@` menu, so it keeps the recorded mentions
              // that its text still has and adds no new ones.
              onEdit?.(
                {
                  message: editedContent,
                  mentions: placeMentions(editedContent, mentions ?? []),
                },
                messageId
              );
              setContent(editedContent);
              setIsEditing(false);
            }}
            onCancelEdit={() => setIsEditing(false)}
          />
        ) : (
          <div className="flex justify-end">
            {!isMobile && copyEditButton}
            <HumanMessageBubble
              content={content}
              mentions={mentions}
              findKey={chatFindTextKey("user", nodeId)}
            />
          </div>
        )}
        <Section
          flexDirection="row"
          justifyContent="end"
          alignItems="center"
          height="fit"
          gap={0}
          className="mt-1"
        >
          {!isEditing && isMobile && copyEditButton}
          {/* The send time sits under the bubble, at its end. */}
          {!isEditing && timeSent && (
            <Hoverable.Item group="humanMessage" variant="appear-on-hover">
              <div className="px-1">
                <MessageTime timeSent={timeSent} />
              </div>
            </Hoverable.Item>
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
