"use client";

import {
  FiCpu,
  FiImage,
  FiThumbsDown,
  FiThumbsUp,
  FiUser,
  FiEdit2,
  FiChevronRight,
  FiChevronLeft,
  FiTool,
} from "react-icons/fi";
import { FeedbackType } from "../types";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { DanswerDocument } from "@/lib/search/interfaces";
import { SearchSummary, ShowHideDocsButton } from "./SearchSummary";
import { SourceIcon } from "@/components/SourceIcon";
import { ThreeDots } from "react-loader-spinner";
import { SkippedSearch } from "./SkippedSearch";
import remarkGfm from "remark-gfm";
import { CopyButton } from "@/components/CopyButton";
import { ChatFileType, FileDescriptor, ToolCallMetadata } from "../interfaces";
import {
  IMAGE_GENERATION_TOOL_NAME,
  SEARCH_TOOL_NAME,
} from "../tools/constants";
import { ToolRunDisplay } from "../tools/ToolRunningAnimation";
import { Hoverable } from "@/components/Hoverable";
import { DocumentPreview } from "../files/documents/DocumentPreview";
import { InMessageImage } from "../files/images/InMessageImage";
import { CodeBlock } from "./CodeBlock";
import rehypePrism from "rehype-prism-plus";

// Prism stuff
import Prism from "prismjs";

import "prismjs/themes/prism-tomorrow.css";
import "./custom-code-styles.css";
import { Persona } from "@/app/admin/assistants/interfaces";

import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

const TOOLS_WITH_CUSTOM_HANDLING = [
  SEARCH_TOOL_NAME,
  IMAGE_GENERATION_TOOL_NAME,
];

function FileDisplay({ files }: { files: FileDescriptor[] }) {
  const imageFiles = files.filter((file) => file.type === ChatFileType.IMAGE);
  const nonImgFiles = files.filter((file) => file.type !== ChatFileType.IMAGE);

  return (
    <>
      {nonImgFiles && nonImgFiles.length > 0 && (
        <div className="mt-2 mb-4">
          <div className="flex flex-col gap-2">
            {nonImgFiles.map((file) => {
              return (
                <div key={file.id} className="w-fit">
                  <DocumentPreview
                    fileName={file.name || file.id}
                    maxWidth="max-w-64"
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}
      {imageFiles && imageFiles.length > 0 && (
        <div className="mt-2 mb-4">
          <div className="flex flex-wrap gap-2">
            {imageFiles.map((file) => {
              return <InMessageImage key={file.id} fileId={file.id} />;
            })}
          </div>
        </div>
      )}
    </>
  );
}

export const AIMessage = ({
  alternativeAssistant,
  messageId,
  content,
  files,
  query,
  personaName,
  citedDocuments,
  toolCall,
  isComplete,
  hasDocs,
  handleFeedback,
  isCurrentlyShowingRetrieved,
  handleShowRetrieved,
  handleSearchQueryEdit,
  handleForceSearch,
  retrievalDisabled,
  currentPersona,
}: {
  alternativeAssistant?: Persona | null;
  currentPersona: Persona;
  messageId: number | null;
  content: string | JSX.Element;
  files?: FileDescriptor[];
  query?: string;
  personaName?: string;
  citedDocuments?: [string, DanswerDocument][] | null;
  toolCall?: ToolCallMetadata;
  isComplete?: boolean;
  hasDocs?: boolean;
  handleFeedback?: (feedbackType: FeedbackType) => void;
  isCurrentlyShowingRetrieved?: boolean;
  handleShowRetrieved?: (messageNumber: number | null) => void;
  handleSearchQueryEdit?: (query: string) => void;
  handleForceSearch?: () => void;
  retrievalDisabled?: boolean;
}) => {
  const [isReady, setIsReady] = useState(false);
  useEffect(() => {
    Prism.highlightAll();
    setIsReady(true);
  }, []);

  // this is needed to give Prism a chance to load
  if (!isReady) {
    return <div />;
  }

  if (!isComplete) {
    const trimIncompleteCodeSection = (
      content: string | JSX.Element
    ): string | JSX.Element => {
      if (typeof content === "string") {
        const pattern = /```[a-zA-Z]+[^\s]*$/;
        const match = content.match(pattern);
        if (match && match.index && match.index > 3) {
          const newContent = content.slice(0, match.index - 3);
          return newContent;
        }
        return content;
      }
      return content;
    };

    content = trimIncompleteCodeSection(content);
  }

  const shouldShowLoader =
    !toolCall || (toolCall.tool_name === SEARCH_TOOL_NAME && !content);
  const defaultLoader = shouldShowLoader ? (
    <div className="my-auto text-sm">
      <ThreeDots
        height="30"
        width="50"
        color="#3b82f6"
        ariaLabel="grid-loading"
        radius="12.5"
        wrapperStyle={{}}
        wrapperClass=""
        visible={true}
      />
    </div>
  ) : undefined;

  return (
    <div className={"flex -mr-6 w-full pb-5 lg:px-28"}>
      <div className="relative mx-auto w-full 2xl:w-searchbar-sm 3xl:w-searchbar">
        <div className="">
          <div className="flex">
            <AssistantIcon
              size="large"
              assistant={alternativeAssistant || currentPersona}
            />

            <div className="my-auto ml-2 font-bold text-emphasis">
              {personaName || "enMedD AI"}
            </div>

            {query === undefined &&
              hasDocs &&
              handleShowRetrieved !== undefined &&
              isCurrentlyShowingRetrieved !== undefined &&
              !retrievalDisabled && (
                <div className="absolute flex ml-8 w-message-xs 2xl:w-message-sm 3xl:w-message-default">
                  <div className="ml-auto">
                    <ShowHideDocsButton
                      messageId={messageId}
                      isCurrentlyShowingRetrieved={isCurrentlyShowingRetrieved}
                      handleShowRetrieved={handleShowRetrieved}
                    />
                  </div>
                </div>
              )}
          </div>

          {/* <div className="pt-2 pl-12 break-words w-full sm:w-message-xs 2xl:w-message-sm 3xl:w-message-default"> */}
          <div className="pl-12 break-words w-full">
            {(!toolCall || toolCall.tool_name === SEARCH_TOOL_NAME) && (
              <>
                {query !== undefined &&
                  handleShowRetrieved !== undefined &&
                  isCurrentlyShowingRetrieved !== undefined &&
                  !retrievalDisabled && (
                    <div className="my-1">
                      <SearchSummary
                        query={query}
                        hasDocs={hasDocs || false}
                        messageId={messageId}
                        isCurrentlyShowingRetrieved={
                          isCurrentlyShowingRetrieved
                        }
                        handleShowRetrieved={handleShowRetrieved}
                        handleSearchQueryEdit={handleSearchQueryEdit}
                      />
                    </div>
                  )}
                {handleForceSearch &&
                  content &&
                  query === undefined &&
                  !hasDocs &&
                  !retrievalDisabled && (
                    <div className="my-1">
                      <SkippedSearch handleForceSearch={handleForceSearch} />
                    </div>
                  )}
              </>
            )}

            {toolCall &&
              !TOOLS_WITH_CUSTOM_HANDLING.includes(toolCall.tool_name) && (
                <div className="my-2">
                  <ToolRunDisplay
                    toolName={
                      toolCall.tool_result && content
                        ? `Used "${toolCall.tool_name}"`
                        : `Using "${toolCall.tool_name}"`
                    }
                    toolLogo={<FiTool size={15} className="my-auto mr-1" />}
                    isRunning={!toolCall.tool_result || !content}
                  />
                </div>
              )}

            {toolCall &&
              toolCall.tool_name === IMAGE_GENERATION_TOOL_NAME &&
              !toolCall.tool_result && (
                <div className="my-2">
                  <ToolRunDisplay
                    toolName={`Generating images`}
                    toolLogo={<FiImage size={15} className="my-auto mr-1" />}
                    isRunning={!toolCall.tool_result}
                  />
                </div>
              )}

            {content ? (
              <>
                <FileDisplay files={files || []} />

                {typeof content === "string" ? (
                  <ReactMarkdown
                    key={messageId}
                    className="max-w-full prose"
                    components={{
                      a: (props) => {
                        const { node, ...rest } = props;
                        // for some reason <a> tags cause the onClick to not apply
                        // and the links are unclickable
                        // TODO: fix the fact that you have to double click to follow link
                        // for the first link
                        return (
                          <a
                            key={node?.position?.start?.offset}
                            onClick={() =>
                              rest.href
                                ? window.open(rest.href, "_blank")
                                : undefined
                            }
                            className="cursor-pointer text-primary hover:text-primary-foreground"
                            // href={rest.href}
                            // target="_blank"
                            // rel="noopener noreferrer"
                          >
                            {rest.children}
                          </a>
                        );
                      },
                      code: (props) => (
                        <CodeBlock {...props} content={content as string} />
                      ),
                      p: ({ node, ...props }) => (
                        <p {...props} className="text-default" />
                      ),
                    }}
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[[rehypePrism, { ignoreMissing: true }]]}
                  >
                    {content}
                  </ReactMarkdown>
                ) : (
                  content
                )}
              </>
            ) : isComplete ? null : (
              defaultLoader
            )}
            {citedDocuments && citedDocuments.length > 0 && (
              <div className="mt-2 flex flex-col gap-1">
                <b className="text-sm text-emphasis">Sources:</b>
                <div className="flex flex-wrap gap-2">
                  {citedDocuments
                    .filter(([_, document]) => document.semantic_identifier)
                    .map(([citationKey, document], ind) => {
                      const display = (
                        <Badge variant="secondary">
                          <div className="my-auto mr-1">
                            <SourceIcon
                              sourceType={document.source_type}
                              iconSize={16}
                            />
                          </div>
                          [{citationKey}] {document!.semantic_identifier}
                        </Badge>
                      );
                      if (document.link) {
                        return (
                          <a
                            key={document.document_id}
                            href={document.link}
                            target="_blank"
                            className="cursor-pointer"
                          >
                            {display}
                          </a>
                        );
                      } else {
                        return (
                          <div
                            key={document.document_id}
                            className="cursor-default"
                          >
                            {display}
                          </div>
                        );
                      }
                    })}
                </div>
              </div>
            )}
          </div>
          {handleFeedback && (
            <div className="flex flex-row gap-x-0.5 ml-12 mt-1.5">
              <CopyButton content={content.toString()} />
              <Hoverable onClick={() => handleFeedback("like")}>
                <FiThumbsUp />
              </Hoverable>
              <Hoverable onClick={() => handleFeedback("dislike")}>
                <FiThumbsDown />
              </Hoverable>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

function MessageSwitcher({
  currentPage,
  totalPages,
  handlePrevious,
  handleNext,
}: {
  currentPage: number;
  totalPages: number;
  handlePrevious: () => void;
  handleNext: () => void;
}) {
  return (
    <div className="flex items-center text-sm space-x-0.5">
      <Hoverable onClick={currentPage === 1 ? undefined : handlePrevious}>
        <FiChevronLeft />
      </Hoverable>
      <span className="select-none text-emphasis text-medium">
        {currentPage} / {totalPages}
      </span>
      <Hoverable onClick={currentPage === totalPages ? undefined : handleNext}>
        <FiChevronRight />
      </Hoverable>
    </div>
  );
}

import logo from "../../../public/logo.png";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";

export const HumanMessage = ({
  content,
  files,
  messageId,
  otherMessagesCanSwitchTo,
  onEdit,
  onMessageSelection,
}: {
  content: string;
  files?: FileDescriptor[];
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onEdit?: (editedContent: string) => void;
  onMessageSelection?: (messageId: number) => void;
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(content);

  useEffect(() => {
    if (!isEditing) {
      setEditedContent(content);
    }
  }, [content]);

  useEffect(() => {
    if (textareaRef.current) {
      // Focus the textarea
      textareaRef.current.focus();
      // Move the cursor to the end of the text
      textareaRef.current.selectionStart = textareaRef.current.value.length;
      textareaRef.current.selectionEnd = textareaRef.current.value.length;
    }
  }, [isEditing]);

  const handleEditSubmit = () => {
    if (editedContent.trim() !== content.trim()) {
      onEdit?.(editedContent);
    }
    setIsEditing(false);
  };

  const currentMessageInd = messageId
    ? otherMessagesCanSwitchTo?.indexOf(messageId)
    : undefined;

  return (
    <div
      className="relative flex w-full pb-5 -mr-6 lg:px-28"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="w-full mx-auto 2xl:w-searchbar-sm 3xl:w-searchbar relative">
        <div className="">
          <div className="flex">
            <div className="p-1 mx-1 bg-blue-400 rounded-regular h-fit">
              <div className="text-inverted">
                <FiUser size={25} className="mx-auto my-auto" />
              </div>
            </div>

            <div className="my-auto ml-2 font-bold text-emphasis">You</div>
          </div>
          {/*  <div className="flex flex-wrap pt-2 pl-12 w-full sm:w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar-default"> */}
          <div className="flex flex-wrap pt-2 pl-12 w-full">
            <div className={`break-words ${isEditing ? "w-full" : "w-auto"}`}>
              <FileDisplay files={files || []} />
              {isEditing ? (
                <div>
                  <div
                    className={`
                      opacity-100
                      w-full
                      flex
                      flex-col
                      border 
                      border-border 
                      rounded-regular 
                      pb-2
                      [&:has(textarea:focus)]::ring-1
                      [&:has(textarea:focus)]::ring-black
                    `}
                  >
                    <Textarea
                      ref={textareaRef}
                      className={`
                      m-0 
                      focus-visible:!ring-0
                      focus-visible:!ring-offset-0
                      w-full 
                      h-auto
                      shrink
                      border-0
                      !rounded-regular 
                      whitespace-normal 
                      break-word
                      overscroll-contain
                      outline-none 
                      placeholder-gray-400 
                      resize-none
                      pl-4
                      overflow-y-auto
                      pr-12 
                      py-4`}
                      aria-multiline
                      role="textarea"
                      value={editedContent}
                      style={{ scrollbarWidth: "thin" }}
                      onChange={(e) => {
                        setEditedContent(e.target.value);
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
                    <div className="flex justify-end gap-2 pr-4 mt-2">
                      <Button onClick={handleEditSubmit}>Submit</Button>
                      <Button
                        onClick={() => {
                          setEditedContent(content);
                          setIsEditing(false);
                        }}
                        variant="destructive"
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                </div>
              ) : typeof content === "string" ? (
                <div className="relative">
                  <div className="flex flex-col max-w-full prose preserve-lines">
                    {content}
                  </div>
                  {onEdit &&
                    isHovered &&
                    !isEditing &&
                    (!files || files.length === 0) && (
                      <div className="bg-hover absolute right-0 -top-[38px] xl:left-[calc(100%_+_10px)] xl:right-auto xl:top-0 rounded">
                        <Hoverable
                          onClick={() => {
                            setIsEditing(true);
                            setIsHovered(false);
                          }}
                        >
                          <FiEdit2 />
                        </Hoverable>
                      </div>
                    )}
                </div>
              ) : (
                content
              )}
            </div>
          </div>
          <div className="flex flex-col md:flex-row gap-x-0.5 ml-12 mt-1">
            {currentMessageInd !== undefined &&
              onMessageSelection &&
              otherMessagesCanSwitchTo &&
              otherMessagesCanSwitchTo.length > 1 && (
                <div className="mr-2">
                  <MessageSwitcher
                    currentPage={currentMessageInd + 1}
                    totalPages={otherMessagesCanSwitchTo.length}
                    handlePrevious={() =>
                      onMessageSelection(
                        otherMessagesCanSwitchTo[currentMessageInd - 1]
                      )
                    }
                    handleNext={() =>
                      onMessageSelection(
                        otherMessagesCanSwitchTo[currentMessageInd + 1]
                      )
                    }
                  />
                </div>
              )}
            {/* {onEdit &&
            isHovered &&
            !isEditing &&
            (!files || files.length === 0) ? (
              <div className="bg-red-500 absolute">
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
            )} */}
          </div>
        </div>
      </div>
    </div>
  );
};
