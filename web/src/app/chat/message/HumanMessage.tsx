"use client";

import React, { useEffect, useRef, useState } from "react";
import { FileDescriptor } from "@/app/chat/interfaces";
import "katex/dist/katex.min.css";
import MessageSwitcher from "@/app/chat/message/MessageSwitcher";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Button from "@/refresh-components/buttons/Button";
import { SvgEdit } from "@opal/icons";
import FileDisplay from "@/app/chat/message/FileDisplay";
import { useTripleClickSelect } from "@/hooks/useTripleClickSelect";

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
          className={cn(
            "w-full h-full resize-none outline-none bg-transparent overflow-y-scroll whitespace-normal break-word"
          )}
          aria-multiline
          role="textarea"
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
        <div className="flex justify-end gap-2">
          <Button onClick={handleSubmit}>Submit</Button>
          <Button secondary onClick={handleCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

interface HumanMessageProps {
  // Content and display
  content: string;
  files?: FileDescriptor[];

  // Message navigation - nodeId for tree position, messageId for editing
  nodeId: number;
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;

  // Editing functionality - takes (editedContent, messageId) to allow stable callback reference
  onEdit?: (editedContent: string, messageId: number) => void;

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
    prev.disableSwitchingForStreaming === next.disableSwitchingForStreaming &&
    prev.otherMessagesCanSwitchTo === next.otherMessagesCanSwitchTo &&
    prev.onEdit === next.onEdit
    // Skip: stopGenerating, onMessageSelection (inline function props)
  );
}

const HumanMessage = React.memo(function HumanMessage({
  content: initialContent,
  files,
  nodeId,
  messageId,
  otherMessagesCanSwitchTo,
  onEdit,
  onMessageSelection,
  stopGenerating = () => null,
  disableSwitchingForStreaming = false,
}: HumanMessageProps) {
  // TODO (@raunakab):
  //
  // This is some duplicated state that is patching a memoization issue with `HumanMessage`.
  // Fix this later.
  const [content, setContent] = useState(initialContent);

  const [isEditing, setIsEditing] = useState(false);

  // Ref for the text content element (for triple-click selection)
  const textContentRef = useRef<HTMLDivElement>(null);
  const handleTripleClick = useTripleClickSelect(textContentRef);

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

  return (
    <div
      id="onyx-human-message"
      className="group flex flex-col justify-end pt-5 pb-1 w-full -mr-6 relative"
    >
      <FileDisplay alignBubble files={files || []} />
      <div className="flex flex-wrap justify-end break-words">
        {isEditing ? (
          <MessageEditing
            content={content}
            onSubmitEdit={(editedContent) => {
              // Don't update UI for edits that can't be persisted
              if (messageId === undefined || messageId === null) {
                setIsEditing(false);
                return;
              }
              onEdit?.(editedContent, messageId);
              setContent(editedContent);
              setIsEditing(false);
            }}
            onCancelEdit={() => setIsEditing(false)}
          />
        ) : typeof content === "string" ? (
          <>
            <div className="md:max-w-[25rem] flex basis-[100%] md:basis-auto justify-end md:order-1">
              <div
                ref={textContentRef}
                className={
                  "max-w-[25rem] whitespace-break-spaces rounded-t-16 rounded-bl-16 bg-background-tint-02 py-2 px-3 cursor-text"
                }
                onMouseDown={handleTripleClick}
                onCopy={(e) => {
                  e.preventDefault();
                  const selection = window.getSelection();
                  if (!selection || !selection.rangeCount) {
                    e.clipboardData.setData("text/plain", content);
                    return;
                  }

                  const range = selection.getRangeAt(0);
                  const selectedText = selection
                    .toString()
                    .replace(/\n{2,}/g, "\n")
                    .trim();

                  // Check if selection is within this element using DOM containment
                  if (
                    textContentRef.current?.contains(
                      range.commonAncestorContainer
                    )
                  ) {
                    e.clipboardData.setData("text/plain", selectedText);
                  } else {
                    e.clipboardData.setData("text/plain", content);
                  }
                }}
              >
                <Text as="p" mainContentBody>
                  {content}
                </Text>
              </div>
            </div>
            {onEdit && !isEditing && (!files || files.length === 0) && (
              <div className="flex flex-row gap-1 p-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <CopyIconButton
                  getCopyText={() => content}
                  tertiary
                  data-testid="HumanMessage/copy-button"
                />
                <IconButton
                  icon={SvgEdit}
                  tertiary
                  tooltip="Edit"
                  onClick={() => setIsEditing(true)}
                  data-testid="HumanMessage/edit-button"
                />
              </div>
            )}
          </>
        ) : (
          <>
            <div
              className={cn(
                "my-auto",
                onEdit && !isEditing && (!files || files.length === 0)
                  ? "opacity-0 group-hover:opacity-100 transition-opacity"
                  : "invisible"
              )}
            >
              <IconButton
                icon={SvgEdit}
                onClick={() => setIsEditing(true)}
                tertiary
                tooltip="Edit"
              />
            </div>
            <div className="ml-auto rounded-lg p-1">{content}</div>
          </>
        )}
        <div className="md:min-w-[100%] flex justify-end order-1 mt-1">
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
        </div>
      </div>
    </div>
  );
}, arePropsEqual);

export default HumanMessage;
