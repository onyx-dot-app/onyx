"use client";

import {
  FiEdit2,
  FiChevronRight,
  FiChevronLeft,
  FiTool,
  FiGlobe,
} from "react-icons/fi";
import { FeedbackType } from "../types";
import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import {
  OnyxDocument,
  FilteredOnyxDocument,
  MinimalOnyxDocument,
} from "@/lib/search/interfaces";
import { SearchSummary, UserKnowledgeFiles } from "./SearchSummary";
import { SkippedSearch } from "./SkippedSearch";
import remarkGfm from "remark-gfm";
import { CopyButton } from "@/components/CopyButton";
import { ChatFileType, FileDescriptor, ToolCallMetadata } from "../interfaces";
import {
  IMAGE_GENERATION_TOOL_NAME,
  SEARCH_TOOL_NAME,
  INTERNET_SEARCH_TOOL_NAME,
} from "../tools/constants";
import { ToolRunDisplay } from "../tools/ToolRunningAnimation";
import { Hoverable, HoverableIcon } from "@/components/Hoverable";
import { DocumentPreview } from "../files/documents/DocumentPreview";
import { InMessageImage } from "../files/images/InMessageImage";
import { CodeBlock } from "./CodeBlock";
import rehypePrism from "rehype-prism-plus";
import "prismjs/themes/prism-tomorrow.css";
import "./custom-code-styles.css";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { LikeFeedback, DislikeFeedback } from "@/components/icons/icons";
import {
  CustomTooltip,
  TooltipGroup,
} from "@/components/tooltip/CustomTooltip";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useMouseTracking } from "./hooks";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import GeneratingImageDisplay from "../tools/GeneratingImageDisplay";
import RegenerateOption from "../RegenerateOption";
import { LlmDescriptor } from "@/lib/hooks";
import { ContinueGenerating } from "./ContinueMessage";
import { MemoizedAnchor, MemoizedParagraph } from "./MemoizedTextComponents";
import { extractCodeText, preprocessLaTeX } from "./codeUtils";
import ToolResult from "../../../components/tools/ToolResult";
import CsvContent from "../../../components/tools/CSVContent";
import {
  FilesSeeMoreBlock,
  SeeMoreBlock,
} from "@/components/chat/sources/SourceCard";
import { FileSourceCard, SourceCard } from "./SourcesDisplay";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { copyAll, handleCopy } from "./copyingUtils";
import { transformLinkUri } from "@/lib/utils";
import { ThinkingBox } from "./thinkingBox/ThinkingBox";
import {
  hasCompletedThinkingTokens,
  hasPartialThinkingTokens,
  extractThinkingContent,
  isThinkingComplete,
  removeThinkingTokens,
} from "../utils/thinkingTokens";
import { FileResponse } from "../my-documents/DocumentsContext";

const TOOLS_WITH_CUSTOM_HANDLING = [
  SEARCH_TOOL_NAME,
  INTERNET_SEARCH_TOOL_NAME,
  IMAGE_GENERATION_TOOL_NAME,
];

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
  const [expandedKnowledge, setExpandedKnowledge] = useState(false);
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

function FileResponseDisplay({
  files,
  alignBubble,
  setPresentingDocument,
}: {
  files: FileResponse[];
  alignBubble?: boolean;
  setPresentingDocument: (document: MinimalOnyxDocument) => void;
}) {
  if (!files || files.length === 0) {
    return null;
  }

  return (
    <div
      id="onyx-file-response"
      className={`${alignBubble && "ml-auto"} mt-2 auto mb-4`}
    >
      <div className="flex flex-col gap-2">
        {files.map((file) => {
          return (
            <div key={file.id} className="w-fit">
              <DocumentPreview
                fileName={file.name || file.document_id}
                alignBubble={alignBubble}
                open={() =>
                  setPresentingDocument({
                    document_id: file.document_id,
                    semantic_identifier: file.name || file.document_id,
                  })
                }
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export const AIMessage = ({
  userKnowledgeFiles = [],
  regenerate,
  overriddenModel,
  continueGenerating,
  shared,
  isActive,
  toggleDocumentSelection,
  alternativeAssistant,
  docs,
  messageId,
  content,
  files,
  selectedDocuments,
  query,
  citedDocuments,
  toolCall,
  isComplete,
  hasDocs,
  handleFeedback,
  handleSearchQueryEdit,
  handleForceSearch,
  retrievalDisabled,
  currentPersona,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  setPresentingDocument,
  index,
  documentSidebarVisible,
  removePadding,
}: {
  userKnowledgeFiles?: FileResponse[];
  index?: number;
  shared?: boolean;
  isActive?: boolean;
  continueGenerating?: () => void;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (messageId: number) => void;
  selectedDocuments?: OnyxDocument[] | null;
  toggleDocumentSelection?: () => void;
  docs?: OnyxDocument[] | null;
  alternativeAssistant?: MinimalPersonaSnapshot | null;
  currentPersona: MinimalPersonaSnapshot;
  messageId: number | null;
  content: string | JSX.Element;
  files?: FileDescriptor[];
  query?: string;
  citedDocuments?: [string, OnyxDocument][] | null;
  toolCall?: ToolCallMetadata | null;
  isComplete?: boolean;
  documentSidebarVisible?: boolean;
  hasDocs?: boolean;
  handleFeedback?: (feedbackType: FeedbackType) => void;
  handleSearchQueryEdit?: (query: string) => void;
  handleForceSearch?: () => void;
  retrievalDisabled?: boolean;
  overriddenModel?: string;
  regenerate?: (modelOverRide: LlmDescriptor) => Promise<void>;
  setPresentingDocument: (document: MinimalOnyxDocument) => void;
  removePadding?: boolean;
}) => {
  const toolCallGenerating = toolCall && !toolCall.tool_result;

  // Check if content contains thinking tokens (complete or partial)
  const hasThinkingTokens = useMemo(() => {
    return (
      hasCompletedThinkingTokens(content) || hasPartialThinkingTokens(content)
    );
  }, [content]);

  // Extract thinking content
  const thinkingContent = useMemo(() => {
    if (!hasThinkingTokens) return "";
    return extractThinkingContent(content);
  }, [content, hasThinkingTokens]);

  // Track if thinking is complete
  const isThinkingTokenComplete = useMemo(() => {
    return isThinkingComplete(thinkingContent);
  }, [thinkingContent]);

  // Extract final content (remove thinking tokens)
  const finalContent = useMemo(() => {
    if (!hasThinkingTokens) return content;
    return removeThinkingTokens(content);
  }, [content, hasThinkingTokens]);

  // Only show the message content when we've completed the thinking section
  // or there are no thinking tokens to begin with
  const shouldShowContent = useMemo(() => {
    if (!hasThinkingTokens) return true;

    // If the message is complete, we always show the content
    if (isComplete) return true;

    // If thinking is not complete, we don't show the content yet
    if (!isThinkingTokenComplete) return false;

    // If thinking is complete but we're not done with the message yet,
    // only show the content if there's actually something to show
    const cleanedContent =
      typeof finalContent === "string" ? finalContent.trim() : finalContent;

    return !!cleanedContent && cleanedContent !== "";
  }, [hasThinkingTokens, isComplete, isThinkingTokenComplete, finalContent]);

  const processContent = (content: string | JSX.Element) => {
    if (typeof content !== "string") {
      return content;
    }

    const codeBlockRegex = /```(\w*)\n[\s\S]*?```|```[\s\S]*?$/g;
    const matches = content.match(codeBlockRegex);

    if (matches) {
      content = matches.reduce((acc, match) => {
        if (!match.match(/```\w+/)) {
          return acc.replace(match, match.replace("```", "```plaintext"));
        }
        return acc;
      }, content);

      const lastMatch = matches[matches.length - 1];
      if (lastMatch && !lastMatch.endsWith("```")) {
        return preprocessLaTeX(content);
      }
    }
    const processed = preprocessLaTeX(content);

    return processed + (!isComplete && !toolCallGenerating ? " [*]() " : "");
  };

  const finalContentProcessed = processContent(finalContent as string);

  const [isRegenerateDropdownVisible, setIsRegenerateDropdownVisible] =
    useState(false);
  const { isHovering, trackedElementRef, hoverElementRef } = useMouseTracking();

  const settings = useContext(SettingsContext);
  // this is needed to give Prism a chance to load

  const selectedDocumentIds =
    selectedDocuments?.map((document) => document.document_id) || [];
  const citedDocumentIds: string[] = [];

  citedDocuments?.forEach((doc) => {
    citedDocumentIds.push(doc[1].document_id);
  });

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

  let filteredDocs: FilteredOnyxDocument[] = [];

  if (docs) {
    filteredDocs = docs
      .filter(
        (doc, index, self) =>
          doc.document_id &&
          doc.document_id !== "" &&
          index === self.findIndex((d) => d.document_id === doc.document_id)
      )
      .filter((doc) => {
        return citedDocumentIds.includes(doc.document_id);
      })
      .map((doc: OnyxDocument, ind: number) => {
        return {
          ...doc,
          included: selectedDocumentIds.includes(doc.document_id),
        };
      });
  }

  const paragraphCallback = useCallback(
    (props: any) => <MemoizedParagraph>{props.children}</MemoizedParagraph>,
    []
  );

  const anchorCallback = useCallback(
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={setPresentingDocument!}
        docs={docs}
        userFiles={userKnowledgeFiles}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
    [docs]
  );

  const currentMessageInd = messageId
    ? otherMessagesCanSwitchTo?.indexOf(messageId)
    : undefined;

  const webSourceDomains: string[] = Array.from(
    new Set(
      docs
        ?.filter((doc) => doc.source_type === "web")
        .map((doc) => {
          try {
            const url = new URL(doc.link);
            return `https://${url.hostname}`;
          } catch {
            return doc.link; // fallback to full link if parsing fails
          }
        }) || []
    )
  );

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      b: ({ node, className, children }: any) => {
        return <span className={className}>{children}</span>;
      },
      code: ({ node, className, children }: any) => {
        const codeText = extractCodeText(
          node,
          finalContentProcessed as string,
          children
        );

        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [anchorCallback, paragraphCallback, finalContentProcessed]
  );
  const markdownRef = useRef<HTMLDivElement>(null);

  // Process selection copying with HTML formatting

  const renderedMarkdown = useMemo(() => {
    if (typeof finalContentProcessed !== "string") {
      return finalContentProcessed;
    }

    return (
      <ReactMarkdown
        className="prose dark:prose-invert max-w-full text-base"
        components={markdownComponents}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
        urlTransform={transformLinkUri}
      >
        {finalContentProcessed}
      </ReactMarkdown>
    );
  }, [finalContentProcessed, markdownComponents]);

  const includeMessageSwitcher =
    currentMessageInd !== undefined &&
    onMessageSelection &&
    otherMessagesCanSwitchTo &&
    otherMessagesCanSwitchTo.length > 1;

  let otherMessage: number | undefined = undefined;
  if (currentMessageInd && otherMessagesCanSwitchTo) {
    otherMessage = otherMessagesCanSwitchTo[currentMessageInd - 1];
  }

  return (
    <div
      id={isComplete ? "onyx-ai-message" : undefined}
      ref={trackedElementRef}
      className={`py-5  ml-4 lg:px-5 relative flex
        
        ${removePadding && "!pl-24 -mt-12"}`}
    >
      <div
        className={`mx-auto ${
          shared ? "w-full" : "w-[90%]"
        }  max-w-message-max`}
      >
        <div className={`lg:mr-12 ${!shared && "mobile:ml-0 md:ml-8"}`}>
          <div className="flex items-start">
            {!removePadding && (
              <AssistantIcon
                className="mobile:hidden"
                size={24}
                assistant={alternativeAssistant || currentPersona}
              />
            )}

            <div className="w-full">
              <div className="max-w-message-max break-words">
                <div className="w-full desktop:ml-4">
                  <div className="max-w-message-max break-words">
                    {userKnowledgeFiles.length == 0 &&
                      (!toolCall || toolCall.tool_name === SEARCH_TOOL_NAME ? (
                        <>
                          {query !== undefined && (
                            <div className="mb-1">
                              <SearchSummary
                                index={index || 0}
                                query={query}
                                finished={toolCall?.tool_result != undefined}
                                handleSearchQueryEdit={handleSearchQueryEdit}
                                docs={docs || []}
                                toggleDocumentSelection={
                                  toggleDocumentSelection!
                                }
                                userFileSearch={retrievalDisabled ?? false}
                              />
                            </div>
                          )}

                          {handleForceSearch &&
                            content &&
                            query === undefined &&
                            !hasDocs &&
                            !retrievalDisabled && (
                              <div className="mb-1">
                                <SkippedSearch
                                  handleForceSearch={handleForceSearch}
                                />
                              </div>
                            )}
                        </>
                      ) : null)}
                    {userKnowledgeFiles && (
                      <UserKnowledgeFiles
                        userKnowledgeFiles={userKnowledgeFiles}
                      />
                    )}

                    {!userKnowledgeFiles &&
                      toolCall &&
                      !TOOLS_WITH_CUSTOM_HANDLING.includes(
                        toolCall.tool_name
                      ) && (
                        <ToolRunDisplay
                          toolName={
                            toolCall.tool_result && content
                              ? `Used "${toolCall.tool_name}"`
                              : `Using "${toolCall.tool_name}"`
                          }
                          toolLogo={
                            <FiTool size={15} className="my-auto mr-1" />
                          }
                          isRunning={!toolCall.tool_result || !content}
                        />
                      )}
                    {toolCall &&
                      (!files || files.length == 0) &&
                      toolCall.tool_name === IMAGE_GENERATION_TOOL_NAME &&
                      !toolCall.tool_result && <GeneratingImageDisplay />}
                    {toolCall &&
                      toolCall.tool_name === INTERNET_SEARCH_TOOL_NAME && (
                        <ToolRunDisplay
                          toolName={
                            toolCall.tool_result
                              ? `Searched the internet`
                              : `Searching the internet`
                          }
                          toolLogo={
                            <FiGlobe size={15} className="my-auto mr-1" />
                          }
                          isRunning={!toolCall.tool_result}
                        />
                      )}
                    {userKnowledgeFiles.length == 0 &&
                      docs &&
                      docs.length > 0 && (
                        <div
                          className={`mobile:hidden ${
                            (query ||
                              toolCall?.tool_name ===
                                INTERNET_SEARCH_TOOL_NAME) &&
                            "mt-2"
                          }  -mx-8 w-full mb-4 flex relative`}
                        >
                          <div className="w-full">
                            <div className="px-8 flex gap-x-2">
                              {!settings?.isMobile &&
                                docs.length > 0 &&
                                docs
                                  .slice(0, 2)
                                  .map((doc: OnyxDocument, ind: number) => (
                                    <SourceCard
                                      document={doc}
                                      key={ind}
                                      setPresentingDocument={() =>
                                        setPresentingDocument({
                                          document_id: doc.document_id,
                                          semantic_identifier: doc.document_id,
                                        })
                                      }
                                    />
                                  ))}
                              <SeeMoreBlock
                                toggled={documentSidebarVisible!}
                                toggleDocumentSelection={
                                  toggleDocumentSelection!
                                }
                                docs={docs}
                                webSourceDomains={webSourceDomains}
                              />
                            </div>
                          </div>
                        </div>
                      )}

                    {userKnowledgeFiles && userKnowledgeFiles.length > 0 && (
                      <div
                        key={10}
                        className={`mobile:hidden ${
                          (query ||
                            toolCall?.tool_name ===
                              INTERNET_SEARCH_TOOL_NAME) &&
                          "mt-2"
                        }  -mx-8 w-full mb-4 flex relative`}
                      >
                        <div className="w-full">
                          <div className="px-8 flex gap-x-2">
                            {!settings?.isMobile &&
                              userKnowledgeFiles.length > 0 &&
                              userKnowledgeFiles
                                .slice(0, 2)
                                .map((file: FileResponse, ind: number) => (
                                  <FileSourceCard
                                    relevantDocument={docs?.find(
                                      (doc) =>
                                        doc.document_id ===
                                          `FILE_CONNECTOR__${file.file_id}` ||
                                        doc.document_id ===
                                          `USER_FILE_CONNECTOR__${file.file_id}`
                                    )}
                                    key={ind}
                                    document={file}
                                    setPresentingDocument={() =>
                                      setPresentingDocument({
                                        document_id: file.document_id,
                                        semantic_identifier: file.name,
                                      })
                                    }
                                  />
                                ))}

                            {userKnowledgeFiles.length > 2 && (
                              <FilesSeeMoreBlock
                                key={10}
                                toggled={documentSidebarVisible!}
                                toggleDocumentSelection={
                                  toggleDocumentSelection!
                                }
                                files={userKnowledgeFiles}
                              />
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Render thinking box if thinking tokens exist */}
                    {hasThinkingTokens && thinkingContent && (
                      <div className="mb-2">
                        <ThinkingBox
                          content={thinkingContent}
                          isComplete={isComplete || false}
                          isStreaming={!isThinkingTokenComplete || !isComplete}
                        />
                      </div>
                    )}

                    {/* Only show the message content once thinking is complete or if there's no thinking */}
                    {shouldShowContent && (content || files) ? (
                      <>
                        <FileDisplay
                          setPresentingDocument={setPresentingDocument}
                          files={files || []}
                        />
                        {typeof content === "string" ? (
                          <div className="overflow-x-visible max-w-content-max">
                            <div
                              ref={markdownRef}
                              className="focus:outline-none cursor-text select-text"
                              onCopy={(e) => handleCopy(e, markdownRef)}
                            >
                              {renderedMarkdown}
                            </div>
                          </div>
                        ) : (
                          content
                        )}
                      </>
                    ) : isComplete ? null : (
                      <></>
                    )}
                  </div>

                  {!removePadding &&
                    handleFeedback &&
                    (isActive ? (
                      <div
                        className={`
                        flex md:flex-row gap-x-0.5 mt-1
                        transition-transform duration-300 ease-in-out
                        transform opacity-100 "
                  `}
                      >
                        <TooltipGroup>
                          <div className="flex justify-start w-full gap-x-0.5">
                            {includeMessageSwitcher &&
                              otherMessage !== undefined && (
                                <div className="-mx-1 mr-auto">
                                  <MessageSwitcher
                                    currentPage={currentMessageInd + 1}
                                    totalPages={otherMessagesCanSwitchTo.length}
                                    handlePrevious={() => {
                                      onMessageSelection(otherMessage!);
                                    }}
                                    handleNext={() => {
                                      onMessageSelection(otherMessage!);
                                    }}
                                  />
                                </div>
                              )}
                          </div>
                          <CustomTooltip showTick line content="Copy">
                            <CopyButton
                              copyAllFn={() =>
                                copyAll(
                                  finalContentProcessed as string,
                                  markdownRef
                                )
                              }
                            />
                          </CustomTooltip>
                          <CustomTooltip showTick line content="Good response">
                            <HoverableIcon
                              icon={<LikeFeedback />}
                              onClick={() => handleFeedback("like")}
                            />
                          </CustomTooltip>
                          <CustomTooltip showTick line content="Bad response">
                            <HoverableIcon
                              icon={<DislikeFeedback size={16} />}
                              onClick={() => handleFeedback("dislike")}
                            />
                          </CustomTooltip>

                          {regenerate && (
                            <CustomTooltip
                              disabled={isRegenerateDropdownVisible}
                              showTick
                              line
                              content="Regenerate"
                            >
                              <RegenerateOption
                                onDropdownVisibleChange={
                                  setIsRegenerateDropdownVisible
                                }
                                selectedAssistant={currentPersona!}
                                regenerate={regenerate}
                                overriddenModel={overriddenModel}
                              />
                            </CustomTooltip>
                          )}
                        </TooltipGroup>
                      </div>
                    ) : (
                      <div
                        ref={hoverElementRef}
                        className={`
                        absolute -bottom-5
                        z-10
                        invisible ${
                          (isHovering || settings?.isMobile) && "!visible"
                        }
                        opacity-0 ${
                          (isHovering || settings?.isMobile) && "!opacity-100"
                        }
                        flex md:flex-row gap-x-0.5 bg-background-125/40 -mx-1.5 p-1.5 rounded-lg
                        `}
                      >
                        <TooltipGroup>
                          <div className="flex justify-start w-full gap-x-0.5">
                            {includeMessageSwitcher &&
                              otherMessage !== undefined && (
                                <div className="-mx-1 mr-auto">
                                  <MessageSwitcher
                                    currentPage={currentMessageInd + 1}
                                    totalPages={otherMessagesCanSwitchTo.length}
                                    handlePrevious={() => {
                                      onMessageSelection(otherMessage!);
                                    }}
                                    handleNext={() => {
                                      onMessageSelection(otherMessage!);
                                    }}
                                  />
                                </div>
                              )}
                          </div>
                          <CustomTooltip showTick line content="Copy">
                            <CopyButton
                              copyAllFn={() =>
                                copyAll(
                                  finalContentProcessed as string,
                                  markdownRef
                                )
                              }
                            />
                          </CustomTooltip>

                          <CustomTooltip showTick line content="Good response">
                            <HoverableIcon
                              icon={<LikeFeedback />}
                              onClick={() => handleFeedback("like")}
                            />
                          </CustomTooltip>

                          <CustomTooltip showTick line content="Bad response">
                            <HoverableIcon
                              icon={<DislikeFeedback size={16} />}
                              onClick={() => handleFeedback("dislike")}
                            />
                          </CustomTooltip>
                          {regenerate && (
                            <CustomTooltip
                              disabled={isRegenerateDropdownVisible}
                              showTick
                              line
                              content="Regenerate"
                            >
                              <RegenerateOption
                                selectedAssistant={currentPersona!}
                                onDropdownVisibleChange={
                                  setIsRegenerateDropdownVisible
                                }
                                regenerate={regenerate}
                                overriddenModel={overriddenModel}
                              />
                            </CustomTooltip>
                          )}
                        </TooltipGroup>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          </div>
        </div>
        {(!toolCall || toolCall.tool_name === SEARCH_TOOL_NAME) &&
          !query &&
          continueGenerating && (
            <ContinueGenerating handleContinueGenerating={continueGenerating} />
          )}
      </div>
    </div>
  );
};

function MessageSwitcher({
  currentPage,
  totalPages,
  handlePrevious,
  handleNext,
  disableForStreaming,
}: {
  currentPage: number;
  totalPages: number;
  handlePrevious: () => void;
  handleNext: () => void;
  disableForStreaming?: boolean;
}) {
  return (
    <div className="flex items-center text-sm space-x-0.5">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div>
              <Hoverable
                icon={FiChevronLeft}
                onClick={
                  disableForStreaming
                    ? () => null
                    : currentPage === 1
                      ? undefined
                      : handlePrevious
                }
              />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            {disableForStreaming
              ? "Wait for agent message to complete"
              : "Previous"}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <span className="text-text-darker select-none">
        {currentPage} / {totalPages}
      </span>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger>
            <div>
              <Hoverable
                icon={FiChevronRight}
                onClick={
                  disableForStreaming
                    ? () => null
                    : currentPage === totalPages
                      ? undefined
                      : handleNext
                }
              />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            {disableForStreaming
              ? "Wait for agent message to complete"
              : "Next"}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}

export const HumanMessage = ({
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

  let otherMessage: number | undefined = undefined;
  if (currentMessageInd && otherMessagesCanSwitchTo) {
    otherMessage = otherMessagesCanSwitchTo[currentMessageInd - 1];
  }

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
              otherMessage !== undefined &&
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
                      onMessageSelection(otherMessage!);
                    }}
                    handleNext={() => {
                      stopGenerating();
                      onMessageSelection(otherMessage!);
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
