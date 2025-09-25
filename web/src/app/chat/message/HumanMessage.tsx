"use client";

import { FiEdit2 } from "react-icons/fi";
import React, { useEffect, useRef, useState } from "react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ChatFileType, FileDescriptor } from "@/app/chat/interfaces";
import { Hoverable, HoverableIcon } from "@/components/Hoverable";
import { DocumentPreview } from "@/app/chat/components/files/documents/DocumentPreview";
import { InMessageImage } from "@/app/chat/components/files/images/InMessageImage";
import "prismjs/themes/prism-tomorrow.css";
import "./custom-code-styles.css";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ToolResult from "@/components/tools/ToolResult";
import CsvContent from "@/components/tools/CSVContent";
import "katex/dist/katex.min.css";
import { MessageSwitcher } from "@/app/chat/message/MessageSwitcher";
import Button from "@/components-2/buttons/Button";

interface FileDisplayProps {
  files: FileDescriptor[];
  alignBubble?: boolean;
  setPresentingDocument: (document: MinimalOnyxDocument) => void;
}

function FileDisplay({
  files,
  alignBubble,
  setPresentingDocument,
}: FileDisplayProps) {
  const [close, setClose] = useState(true);
  const imageFiles = files.filter((file) => file.type === ChatFileType.IMAGE);
  const textFiles = files.filter(
    (file) => file.type == ChatFileType.PLAIN_TEXT
  );

  const csvImgFiles = files.filter((file) => file.type == ChatFileType.CSV);

  return (
    <>
      {textFiles && textFiles.length > 0 && (
        <div
          id="onyx-file"
          className={` ${alignBubble && "ml-auto"} mt-2 auto mb-4`}
        >
          <div className="flex flex-col gap-2">
            {textFiles.map((file) => {
              return (
                <div key={file.id} className="w-fit">
                  <DocumentPreview
                    fileName={file.name || file.id}
                    alignBubble={alignBubble}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {imageFiles && imageFiles.length > 0 && (
        <div
          id="onyx-image"
          className={` ${alignBubble && "ml-auto"} mt-2 auto mb-4`}
        >
          <div className="flex flex-col gap-2">
            {imageFiles.map((file) => {
              return <InMessageImage key={file.id} fileId={file.id} />;
            })}
          </div>
        </div>
      )}
      {csvImgFiles && csvImgFiles.length > 0 && (
        <div className={` ${alignBubble && "ml-auto"} mt-2 auto mb-4`}>
          <div className="flex flex-col gap-2">
            {csvImgFiles.map((file) => {
              return (
                <div key={file.id} className="w-fit">
                  {close ? (
                    <>
                      <ToolResult
                        csvFileDescriptor={file}
                        close={() => setClose(false)}
                        contentComponent={CsvContent}
                      />
                    </>
                  ) : (
                    <DocumentPreview
                      open={() => setClose(true)}
                      fileName={file.name || file.id}
                      maxWidth="max-w-64"
                      alignBubble={alignBubble}
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

interface HumanMessageProps {
  shared?: boolean;
  content: string;
  files?: FileDescriptor[];
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onEdit?: (editedContent: string) => void;
  onMessageSelection?: (messageId: number) => void;
  stopGenerating?: () => void;
  disableSwitchingForStreaming?: boolean;
  setPresentingDocument: (document: MinimalOnyxDocument) => void;
}

interface EditingAreaProps {
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  editedContent: string;
  setEditedContent: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  originalContent: string;
}

function EditingArea({
  textareaRef,
  editedContent,
  setEditedContent,
  onSubmit,
  onCancel,
  originalContent,
}: EditingAreaProps) {
  return (
    <div className="w-full flex flex-col border rounded-08 p-spacing-interline bg-background-tint-02">
      <textarea
        ref={textareaRef}
        className="w-full h-full overflow-y-hidden whitespace-normal break-word overscroll-contain resize-none overflow-y-auto bg-background-tint-02 outline-none p-padding-button"
        aria-multiline
        role="textarea"
        value={editedContent}
        style={{ scrollbarWidth: "thin" }}
        onChange={(event) => {
          setEditedContent(event.target.value);
          textareaRef.current!.style.height = "auto";
          event.target.style.height = `${event.target.scrollHeight}px`;
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            setEditedContent(originalContent);
            onCancel();
          }
          // Submit edit if "Command Enter" is pressed, like in ChatGPT
          else if (event.key === "Enter" && event.metaKey) {
            onSubmit();
          }
        }}
      />
      <div className="flex flex-row justify-end gap-spacing-inline">
        <Button onClick={onSubmit}>Submit</Button>
        <Button
          secondary
          onClick={() => {
            setEditedContent(originalContent);
            onCancel();
          }}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function HumanMessage({
  content,
  files,
  messageId,
  otherMessagesCanSwitchTo,
  onEdit,
  onMessageSelection,
  shared,
  stopGenerating = () => null,
  disableSwitchingForStreaming = false,
  setPresentingDocument,
}: HumanMessageProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(content);
  useEffect(() => setEditedContent(content), [content]);
  useEffect(() => {
    if (textareaRef.current) {
      // Focus the textarea
      textareaRef.current.focus();
      // Move the cursor to the end of the text
      textareaRef.current.selectionStart = textareaRef.current.value.length;
      textareaRef.current.selectionEnd = textareaRef.current.value.length;
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [isEditing]);

  const handleEditSubmit = () => {
    onEdit?.(editedContent);
    setIsEditing(false);
  };

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
      <div className={`mx-auto ${shared ? "w-full" : "w-[90%]"} max-w-[790px]`}>
        <div className="xl:ml-8">
          <div className="flex flex-col desktop:mr-4">
            <FileDisplay
              alignBubble
              setPresentingDocument={setPresentingDocument}
              files={files || []}
            />

            <div className="flex justify-end">
              <div className="w-full ml-8 flex w-full w-[800px] break-words">
                {isEditing ? (
                  <EditingArea
                    textareaRef={textareaRef}
                    editedContent={editedContent}
                    setEditedContent={setEditedContent}
                    onSubmit={handleEditSubmit}
                    onCancel={() => setIsEditing(false)}
                    originalContent={content}
                  />
                ) : typeof content === "string" ? (
                  <>
                    <div className="ml-auto flex items-center mr-1 mt-2 h-fit mb-auto">
                      {onEdit &&
                      isHovered &&
                      !isEditing &&
                      (!files || files.length === 0) ? (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger>
                              <HoverableIcon
                                icon={<FiEdit2 className="text-text-05" />}
                                onClick={() => {
                                  setIsEditing(true);
                                  setIsHovered(false);
                                }}
                              />
                            </TooltipTrigger>
                            <TooltipContent>Edit</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : (
                        <div className="w-7" />
                      )}
                    </div>

                    <div
                      className={`${
                        !(
                          onEdit &&
                          isHovered &&
                          !isEditing &&
                          (!files || files.length === 0)
                        ) && "ml-auto"
                      } relative flex-none max-w-[70%] mb-auto whitespace-break-spaces rounded-bl-3xl rounded-t-3xl bg-background-neutral-02 px-5 py-2.5`}
                    >
                      {editedContent}
                    </div>
                  </>
                ) : (
                  <>
                    {onEdit &&
                    isHovered &&
                    !isEditing &&
                    (!files || files.length === 0) ? (
                      <div className="my-auto">
                        <Hoverable
                          icon={FiEdit2}
                          onClick={() => {
                            setIsEditing(true);
                            setIsHovered(false);
                          }}
                        />
                      </div>
                    ) : (
                      <div className="h-[27px]" />
                    )}
                    <div className="ml-auto rounded-lg p-1">
                      {editedContent}
                    </div>
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
