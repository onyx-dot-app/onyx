"use client";

import { FiEdit2 } from "react-icons/fi";
import React, { useEffect, useRef, useState, memo } from "react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ChatFileType, FileDescriptor } from "@/app/chat/interfaces";
import { Hoverable, HoverableIcon } from "@/components/Hoverable";
import { DocumentPreview } from "../components/files/documents/DocumentPreview";
import { InMessageImage } from "../components/files/images/InMessageImage";
import "prismjs/themes/prism-tomorrow.css";
import "./custom-code-styles.css";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ToolResult from "../../../components/tools/ToolResult";
import CsvContent from "../../../components/tools/CSVContent";
import "katex/dist/katex.min.css";
import { MessageSwitcher } from "./MessageSwitcher";

function FileDisplay({
  files,
  alignBubble,
  setPresentingDocument,
}: {
  files: FileDescriptor[];
  alignBubble?: boolean;
  setPresentingDocument: (document: MinimalOnyxDocument) => void;
}) {
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

const HumanMessageComponent = ({
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
}: {
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
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  console.log("Rendering HumanMessage");

  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(content);

  useEffect(() => {
    if (!isEditing) {
      setEditedContent(content);
    }
  }, [content, isEditing]);

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
      <div
        className={`text-user-text mx-auto ${
          shared ? "w-full" : "w-[90%]"
        } max-w-[790px]`}
      >
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
                  <div className="w-full">
                    <div
                      className={`
                      opacity-100
                      w-full
                      flex
                      flex-col
                      border 
                      border-border 
                      rounded-lg 
                      pb-2
                      [&:has(textarea:focus)]::ring-1
                      [&:has(textarea:focus)]::ring-black
                    `}
                    >
                      <textarea
                        ref={textareaRef}
                        className={`
                        m-0 
                        w-full 
                        h-auto
                        shrink
                        border-0
                        rounded-lg 
                        overflow-y-hidden
                        whitespace-normal 
                        break-word
                        overscroll-contain
                        outline-none 
                        placeholder-text-400 
                        resize-none
                        text-text-editing-message
                        pl-4
                        overflow-y-auto
                        bg-background
                        pr-12 
                        py-4`}
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
                            setEditedContent(content);
                            setIsEditing(false);
                          }
                          // Submit edit if "Command Enter" is pressed, like in ChatGPT
                          if (e.key === "Enter" && e.metaKey) {
                            handleEditSubmit();
                          }
                        }}
                      />
                      <div className="flex justify-end mt-2 gap-2 pr-4">
                        <button
                          className={`
                          w-fit
                          bg-agent 
                          text-inverted 
                          text-sm
                          rounded-lg 
                          inline-flex 
                          items-center 
                          justify-center 
                          flex-shrink-0 
                          font-medium 
                          min-h-[38px]
                          py-2
                          px-3
                          hover:bg-agent-hovered
                        `}
                          onClick={handleEditSubmit}
                        >
                          Submit
                        </button>
                        <button
                          className={`
                          inline-flex 
                          items-center 
                          justify-center 
                          flex-shrink-0 
                          font-medium 
                          min-h-[38px] 
                          py-2 
                          px-3 
                          w-fit 
                          bg-background-200 
                          text-sm
                          rounded-lg
                          hover:bg-accent-background-hovered-emphasis
                        `}
                          onClick={() => {
                            setEditedContent(content);
                            setIsEditing(false);
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                ) : typeof content === "string" ? (
                  <>
                    <div className="ml-auto flex items-center mr-1 mt-2 h-fit mb-auto">
                      {onEdit &&
                      isHovered &&
                      !isEditing &&
                      (!files || files.length === 0) ? (
                        <TooltipProvider delayDuration={1000}>
                          <Tooltip>
                            <TooltipTrigger>
                              <HoverableIcon
                                icon={<FiEdit2 className="text-text-600" />}
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
                      } relative text-text flex-none max-w-[70%] mb-auto whitespace-break-spaces rounded-3xl bg-user px-5 py-2.5`}
                    >
                      {content}
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
};

// Custom comparison function to prevent unnecessary re-renders
const areEqual = (prevProps: any, nextProps: any) => {
  // Only re-render if the actual message data has changed
  if (prevProps.content !== nextProps.content) {
    console.log("HumanMessage re-render: content changed");
    return false;
  }
  if (prevProps.messageId !== nextProps.messageId) {
    console.log("HumanMessage re-render: messageId changed");
    return false;
  }
  if (
    prevProps.disableSwitchingForStreaming !==
    nextProps.disableSwitchingForStreaming
  ) {
    console.log("HumanMessage re-render: disableSwitchingForStreaming changed");
    return false;
  }

  // Check files array - only if length changed
  if (prevProps.files?.length !== nextProps.files?.length) {
    console.log("HumanMessage re-render: files length changed");
    return false;
  }

  // Ignore all other prop changes including functions and arrays
  // that are just reference changes
  return true;
};

export const HumanMessage = memo(HumanMessageComponent, areEqual);
HumanMessage.displayName = "HumanMessage";
