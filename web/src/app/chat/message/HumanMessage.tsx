"use client";

import React, { useEffect, useRef, useState } from "react";
import { ChatFileType, FileDescriptor } from "@/app/chat/interfaces";
import Attachment from "@/refresh-components/Attachment";
import { InMessageImage } from "@/app/chat/components/files/images/InMessageImage";
import CsvContent from "@/components/tools/CSVContent";
import "katex/dist/katex.min.css";
import MessageSwitcher from "@/app/chat/message/MessageSwitcher";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgEdit from "@/icons/edit";
import Button from "@/refresh-components/buttons/Button";
import SvgCopy from "@/icons/copy";
import { copyAll } from "@/app/chat/message/copyingUtils";
import ExpandableContentWrapper from "@/components/tools/ExpandableContentWrapper";

interface FileDisplayProps {
  files: FileDescriptor[];
  alignBubble?: boolean;
}

interface MessageEditingProps {
  content: string;
  onSubmitEdit: (editedContent: string) => void;
  onCancelEdit: () => void;
}

function FileDisplay({ files, alignBubble }: FileDisplayProps) {
  const [close, setClose] = useState(true);
  const textFiles = files.filter(
    (file) =>
      file.type === ChatFileType.PLAIN_TEXT ||
      file.type === ChatFileType.DOCUMENT
  );
  const imageFiles = files.filter((file) => file.type === ChatFileType.IMAGE);
  const csvFiles = files.filter((file) => file.type === ChatFileType.CSV);

  return (
    <>
      {textFiles.length > 0 && (
        <div
          id="onyx-file"
          className={cn("mt-2 auto", alignBubble && "ml-auto")}
        >
          <div className="flex flex-col gap-2">
            {textFiles.map((file) => (
              <Attachment key={file.id} fileName={file.name || file.id} />
            ))}
          </div>
        </div>
      )}

      {imageFiles.length > 0 && (
        <div
          id="onyx-image"
          className={cn("mt-2 auto", alignBubble && "ml-auto")}
        >
          <div className="flex flex-col gap-2">
            {imageFiles.map((file) => (
              <InMessageImage key={file.id} fileId={file.id} />
            ))}
          </div>
        </div>
      )}

      {csvFiles.length > 0 && (
        <div className={cn("mt-2 auto", alignBubble && "ml-auto")}>
          <div className="flex flex-col gap-2">
            {csvFiles.map((file) => {
              return (
                <div key={file.id} className="w-fit">
                  {close ? (
                    <>
                      <ExpandableContentWrapper
                        fileDescriptor={file}
                        close={() => setClose(false)}
                        ContentComponent={CsvContent}
                      />
                    </>
                  ) : (
                    <Attachment
                      open={() => setClose(true)}
                      fileName={file.name || file.id}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
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
          "w-full h-full border rounded-16 overflow-hidden p-padding-button flex flex-col gap-spacing-interline"
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
        <div className="flex justify-end gap-spacing-interline">
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
  shared?: boolean;

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
  shared,
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
      className="pt-5 pb-1 w-full lg:px-5 flex -mr-6 relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={cn(
          "text-user-text mx-auto max-w-[790px]",
          shared ? "w-full" : "w-[90%]"
        )}
      >
        <div className="xl:ml-8">
          <div className="flex flex-col desktop:mr-4">
            <FileDisplay alignBubble files={files || []} />

            <div className="flex justify-end mt-1">
              <div className="w-full ml-8 flex w-full w-[800px] break-words">
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
                    <div className="ml-auto flex items-center mr-1 h-fit mb-auto">
                      {onEdit &&
                      isHovered &&
                      !isEditing &&
                      (!files || files.length === 0) ? (
                        <div className="flex flex-row items-center justify-center gap-spacing-inline">
                          <IconButton
                            icon={SvgCopy}
                            tertiary
                            tooltip="Copy"
                            onClick={() => copyAll(content)}
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
                        <div className="w-7" />
                      )}
                    </div>

                    <div
                      className={cn(
                        "max-w-[25rem] whitespace-break-spaces rounded-t-16 rounded-bl-16 bg-background-tint-02 py-spacing-interline px-padding-button",
                        !(
                          onEdit &&
                          isHovered &&
                          !isEditing &&
                          (!files || files.length === 0)
                        ) && "ml-auto"
                      )}
                    >
                      <Text mainContentBody>{content}</Text>
                    </div>
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
              </div>
            </div>
          </div>

          <div className="flex flex-col md:flex-row gap-x-0.5 mt-1">
            {currentMessageInd !== undefined &&
              onMessageSelection &&
              otherMessagesCanSwitchTo &&
              otherMessagesCanSwitchTo.length > 1 && (
                <div className="ml-auto mr-3">
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
                </div>
              )}
          </div>
        </div>
      </div>
    </div>
  );
}
