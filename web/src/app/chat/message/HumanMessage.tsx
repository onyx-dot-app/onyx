"use client";

import { useEffect, useRef, useState } from "react";
import { FileDescriptor } from "@/app/chat/interfaces";
import "katex/dist/katex.min.css";
import MessageSwitcher from "@/app/chat/message/MessageSwitcher";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Button from "@/refresh-components/buttons/Button";
import { SvgEdit } from "@opal/icons";
import FileDisplay from "./FileDisplay";

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

  // Message navigation
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (messageId: number) => void;

  // Editing functionality
  onEdit?: (editedContent: string) => void;

  // Streaming and generation
  stopGenerating?: () => void;
  disableSwitchingForStreaming?: boolean;
}

export default function HumanMessage({
  content: initialContent,
  files,
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

  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const currentMessageInd = messageId
    ? otherMessagesCanSwitchTo?.indexOf(messageId)
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
      className="pt-5 pb-1 w-full lg:px-5 flex justify-center -mr-6 relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className={cn("text-user-text max-w-[790px] px-4 w-full")}>
        <FileDisplay alignBubble files={files || []} />
        <div className="flex flex-wrap justify-end break-words">
          {isEditing ? (
            <MessageEditing
              content={content}
              onSubmitEdit={(editedContent) => {
                onEdit?.(editedContent);
                setContent(editedContent);
                setIsEditing(false);
              }}
              onCancelEdit={() => setIsEditing(false)}
            />
          ) : typeof content === "string" ? (
            <>
              <div className="md:max-w-[25rem] flex basis-[100%] md:basis-auto justify-end md:order-1">
                <div
                  className={
                    "max-w-[25rem] whitespace-break-spaces rounded-t-16 rounded-bl-16 bg-background-tint-02 py-2 px-3"
                  }
                >
                  <Text mainContentBody>{content}</Text>
                </div>
              </div>
              {onEdit &&
              isHovered &&
              !isEditing &&
              (!files || files.length === 0) ? (
                <div className="flex flex-row gap-1 p-1">
                  <CopyIconButton
                    getCopyText={() => content}
                    tertiary
                    data-testid="HumanMessage/copy-button"
                  />
                  <IconButton
                    icon={SvgEdit}
                    tertiary
                    tooltip="Edit"
                    onClick={() => {
                      setIsEditing(true);
                      setIsHovered(false);
                    }}
                    data-testid="HumanMessage/edit-button"
                  />
                </div>
              ) : (
                <div className="w-7 h-10" />
              )}
            </>
          ) : (
            <>
              {onEdit &&
              isHovered &&
              !isEditing &&
              (!files || files.length === 0) ? (
                <div className="my-auto">
                  <IconButton
                    icon={SvgEdit}
                    onClick={() => {
                      setIsEditing(true);
                      setIsHovered(false);
                    }}
                    tertiary
                    tooltip="Edit"
                  />
                </div>
              ) : (
                <div className="h-[27px]" />
              )}
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
    </div>
  );
}
