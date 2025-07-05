"use client";

import { FiChevronRight, FiChevronLeft } from "react-icons/fi";
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
import { OnyxDocument } from "@/lib/search/interfaces";
import remarkGfm from "remark-gfm";
import { CopyButton } from "@/components/CopyButton";
import {
  BaseQuestionIdentifier,
  FileDescriptor,
  SubQuestionDetail,
  ToolCallMetadata,
} from "../interfaces";
import { SEARCH_TOOL_NAME } from "../tools/constants";
import { Hoverable, HoverableIcon } from "@/components/Hoverable";
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
import { useMouseTracking } from "./hooks";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import RegenerateOption from "../RegenerateOption";
import { LlmDescriptor } from "@/lib/hooks";
import { ContinueGenerating } from "./ContinueMessage";
import { MemoizedAnchor, MemoizedParagraph } from "./MemoizedTextComponents";
import { extractCodeText, preprocessLaTeX } from "./codeUtils";
import { ThinkingBox } from "./thinkingBox/ThinkingBox";
import {
  hasCompletedThinkingTokens,
  hasPartialThinkingTokens,
  extractThinkingContent,
  isThinkingComplete,
  removeThinkingTokens,
} from "../utils/thinkingTokens";

import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import SubQuestionsDisplay from "./SubQuestionsDisplay";
import { copyAll, handleCopy } from "./copyingUtils";
import { ErrorBanner } from "./Resubmit";
import { transformLinkUri } from "@/lib/utils";

export const AgenticMessage = ({
  isStreamingQuestions,
  isGenerating,
  docSidebarToggled,
  secondLevelAssistantMessage,
  secondLevelGenerating,
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
  query,
  citedDocuments,
  toolCall,
  isComplete,
  handleFeedback,
  currentPersona,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  setPresentingDocument,
  subQuestions,
  agenticDocs,
  secondLevelSubquestions,
  error,
  resubmit,
}: {
  resubmit?: () => void;
  isStreamingQuestions: boolean;
  isGenerating: boolean;
  docSidebarToggled?: boolean;
  secondLevelSubquestions?: SubQuestionDetail[] | null;
  agenticDocs?: OnyxDocument[] | null;
  secondLevelGenerating?: boolean;
  secondLevelAssistantMessage?: string;
  subQuestions: SubQuestionDetail[] | null;
  shared?: boolean;
  isActive?: boolean;
  continueGenerating?: () => void;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (messageId: number) => void;
  toggleDocumentSelection?: (second: boolean) => void;
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
  handleFeedback?: (feedbackType: FeedbackType) => void;
  overriddenModel?: string;
  regenerate?: (modelOverRide: LlmDescriptor) => Promise<void>;
  setPresentingDocument?: (document: OnyxDocument) => void;
  error?: string | null;
}) => {
  const [lastKnownContentLength, setLastKnownContentLength] = useState(0);

  const [allowStreaming, setAllowStreaming] = useState(isComplete);
  const [allowDocuments, setAllowDocuments] = useState(isComplete);

  const alternativeContent = secondLevelAssistantMessage || "";

  const processContent = (incoming: string | JSX.Element) => {
    if (typeof incoming !== "string") return incoming;

    let processed = incoming;

    // Apply thinking tokens processing first
    if (
      hasCompletedThinkingTokens(processed) ||
      hasPartialThinkingTokens(processed)
    ) {
      processed = removeThinkingTokens(processed) as string;
    }

    const codeBlockRegex = /```(\w*)\n[\s\S]*?```|```[\s\S]*?$/g;
    const matches = processed.match(codeBlockRegex);
    if (matches) {
      processed = matches.reduce((acc, match) => {
        if (!match.match(/```\w+/)) {
          return acc.replace(match, match.replace("```", "```plaintext"));
        }
        return acc;
      }, processed);

      const lastMatch = matches[matches.length - 1];
      if (lastMatch && !lastMatch.endsWith("```")) {
        processed = preprocessLaTeX(processed);
      }
    }

    processed = processed.replace(/\[([QD])(\d+)\]/g, (match, type, number) => {
      const citationNumber = parseInt(number, 10);
      return `[[${type}${citationNumber}]]()`;
    });

    processed = processed.replace(/\{\{(\d+)\}\}/g, (match, p1) => {
      const citationNumber = parseInt(p1, 10);
      return `[[${citationNumber}]]()`;
    });

    processed = processed.replace(/\]\](?!\()/g, "]]()");

    return preprocessLaTeX(processed);
  };

  const [streamedContent, setStreamedContent] = useState(
    processContent(content) as string
  );
  const finalContent = processContent(content) as string;
  const finalAlternativeContent = processContent(alternativeContent) as string;

  // Check if content contains thinking tokens
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

  // Enable streaming when thinking tokens are detected
  useEffect(() => {
    if (hasThinkingTokens) {
      setAllowStreaming(true);
    }
  }, [hasThinkingTokens]);

  const isViewingInitialAnswer = true;

  const [isRegenerateDropdownVisible, setIsRegenerateDropdownVisible] =
    useState(false);

  const { isHovering, trackedElementRef, hoverElementRef } = useMouseTracking();

  const settings = useContext(SettingsContext);

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

  const paragraphCallback = useCallback(
    (props: any, fontSize: "sm" | "base" = "base") => (
      <MemoizedParagraph fontSize={fontSize}>
        {props.children}
      </MemoizedParagraph>
    ),
    []
  );
  const [currentlyOpenQuestion, setCurrentlyOpenQuestion] =
    useState<BaseQuestionIdentifier | null>(null);
  const [finishedGenerating, setFinishedGenerating] = useState(!isGenerating);

  useEffect(() => {
    if (streamedContent.length == finalContent.length && !isGenerating) {
      setFinishedGenerating(true);
    }
  }, [streamedContent, finalContent, isGenerating]);

  const openQuestion = useCallback(
    (question: SubQuestionDetail) => {
      setCurrentlyOpenQuestion({
        level: question.level,
        level_question_num: question.level_question_num,
      });
      setTimeout(() => {
        setCurrentlyOpenQuestion(null);
      }, 1000);
    },
    [currentlyOpenQuestion]
  );

  const anchorCallback = useCallback(
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={setPresentingDocument!}
        docs={
          isViewingInitialAnswer
            ? docs && docs.length > 0
              ? docs
              : agenticDocs
            : agenticDocs && agenticDocs.length > 0
              ? agenticDocs
              : docs
        }
        subQuestions={[
          ...(subQuestions || []),
          ...(secondLevelSubquestions || []),
        ]}
        openQuestion={openQuestion}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
    [docs, agenticDocs, isViewingInitialAnswer]
  );

  const currentMessageInd = messageId
    ? otherMessagesCanSwitchTo?.indexOf(messageId)
    : undefined;

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      code: ({ node, className, children }: any) => {
        const codeText = extractCodeText(node, streamedContent, children);
        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [anchorCallback, paragraphCallback, streamedContent]
  );

  const markdownRef = useRef<HTMLDivElement>(null);

  const renderedAlternativeMarkdown = useMemo(() => {
    return (
      <ReactMarkdown
        className="prose dark:prose-invert max-w-full text-base"
        components={{
          ...markdownComponents,
          code: ({ node, className, children }: any) => {
            const altCode = extractCodeText(
              node,
              finalAlternativeContent,
              children
            );
            return (
              <CodeBlock className={className} codeText={altCode}>
                {children}
              </CodeBlock>
            );
          },
        }}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
        urlTransform={transformLinkUri}
      >
        {finalAlternativeContent}
      </ReactMarkdown>
    );
  }, [markdownComponents, finalAlternativeContent]);

  const renderedMarkdown = useMemo(() => {
    return (
      <ReactMarkdown
        className="prose dark:prose-invert max-w-full text-base"
        components={markdownComponents}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
        urlTransform={transformLinkUri}
      >
        {streamedContent +
          (!isComplete && !secondLevelGenerating ? " [*]() " : "")}
      </ReactMarkdown>
    );
  }, [streamedContent, markdownComponents, isComplete]);

  const includeMessageSwitcher =
    currentMessageInd !== undefined &&
    onMessageSelection &&
    otherMessagesCanSwitchTo &&
    otherMessagesCanSwitchTo.length > 1;

  let otherMessage: number | undefined = undefined;
  if (currentMessageInd && otherMessagesCanSwitchTo) {
    otherMessage = otherMessagesCanSwitchTo[currentMessageInd - 1];
  }

  useEffect(() => {
    if (!allowStreaming) {
      return;
    }

    if (typeof finalContent !== "string") return;

    let intervalId: NodeJS.Timeout | null = null;

    intervalId = setInterval(() => {
      setStreamedContent((prev) => {
        if (prev.length < finalContent.length) {
          const nextLength = Math.min(prev.length + 5, finalContent.length);
          return finalContent.slice(0, nextLength);
        } else {
          if (intervalId) clearInterval(intervalId);
          return finalContent;
        }
      });
    }, 10);

    return () => {
      if (intervalId) clearInterval(intervalId);
      setLastKnownContentLength(finalContent.length);
    };
  }, [
    allowStreaming,
    finalContent,
    streamedContent,
    content,
    lastKnownContentLength,
  ]);

  return (
    <div
      id="onyx-ai-message"
      ref={trackedElementRef}
      className={`py-5 ml-4 lg:px-5 relative flex flex-col`}
    >
      <div
        className={`mx-auto ${shared ? "w-full" : "w-[90%]"} max-w-message-max`}
      >
        <div className={`lg:mr-12 ${!shared && "mobile:ml-0 md:ml-8"}`}>
          <div className="flex items-start">
            <AssistantIcon
              className="mobile:hidden"
              size={24}
              assistant={alternativeAssistant || currentPersona}
            />

            <div className="w-full">
              <div className="max-w-message-max break-words">
                <div className="w-full desktop:ml-4">
                  {subQuestions && subQuestions.length > 0 && (
                    <SubQuestionsDisplay
                      isStreamingQuestions={isStreamingQuestions}
                      allowDocuments={() => setAllowDocuments(true)}
                      docSidebarToggled={docSidebarToggled || false}
                      finishedGenerating={finishedGenerating}
                      overallAnswerGenerating={
                        !!(
                          secondLevelSubquestions &&
                          secondLevelSubquestions.length > 0 &&
                          finalContent.length < 8
                        )
                      }
                      showSecondLevel={!isViewingInitialAnswer}
                      currentlyOpenQuestion={currentlyOpenQuestion}
                      allowStreaming={() => setAllowStreaming(true)}
                      subQuestions={subQuestions}
                      secondLevelQuestions={secondLevelSubquestions || []}
                      documents={
                        !allowDocuments
                          ? []
                          : isViewingInitialAnswer
                            ? docs!
                            : agenticDocs!
                      }
                      toggleDocumentSelection={() => {
                        toggleDocumentSelection!(!isViewingInitialAnswer);
                      }}
                      setPresentingDocument={setPresentingDocument!}
                      unToggle={false}
                    />
                  )}
                  {/* Render thinking box if thinking tokens exist */}
                  {hasThinkingTokens && thinkingContent && (
                    <div className="mb-2 mt-1">
                      <ThinkingBox
                        content={thinkingContent}
                        isComplete={isComplete || false}
                        isStreaming={!isThinkingTokenComplete || !isComplete}
                      />
                    </div>
                  )}
                  {/* For debugging purposes */}
                  {/* <SubQuestionProgress subQuestions={subQuestions || []} /> */}
                  {/*  */}
                  {(allowStreaming &&
                    finalContent &&
                    finalContent.length > 8) ||
                  (files && files.length > 0) ? (
                    <>
                      <div className="w-full  py-4 flex flex-col gap-4">
                        <div className="flex items-center gap-x-2 px-4">
                          <div className="text-black text-lg font-medium">
                            Answer
                          </div>
                        </div>

                        <div className="px-4">
                          {typeof content === "string" ? (
                            <div
                              onCopy={(e) => handleCopy(e, markdownRef)}
                              ref={markdownRef}
                              className="overflow-x-visible !text-sm max-w-content-max"
                            >
                              {isViewingInitialAnswer
                                ? renderedMarkdown
                                : renderedAlternativeMarkdown}
                            </div>
                          ) : (
                            content
                          )}
                          {error && (
                            <ErrorBanner error={error} resubmit={resubmit} />
                          )}
                        </div>
                      </div>
                    </>
                  ) : isComplete ? (
                    error && (
                      <p className="mt-2 mx-4 text-red-700 text-sm my-auto">
                        <ErrorBanner error={error} resubmit={resubmit} />
                      </p>
                    )
                  ) : (
                    <>
                      {error && (
                        <ErrorBanner error={error} resubmit={resubmit} />
                      )}
                    </>
                  )}
                  {handleFeedback &&
                    (isActive ? (
                      <div
                        className={`
                          flex md:flex-row gap-x-0.5 mt-1
                          transition-transform duration-300 ease-in-out
                          transform opacity-100 translate-y-0"
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
                                  (isViewingInitialAnswer
                                    ? finalContent
                                    : finalAlternativeContent) as string,
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
                          translate-y-2 ${
                            (isHovering || settings?.isMobile) &&
                            "!translate-y-0"
                          }
                          transition-transform duration-300 ease-in-out
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
                                  (isViewingInitialAnswer
                                    ? finalContent
                                    : finalAlternativeContent) as string,
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
}: {
  currentPage: number;
  totalPages: number;
  handlePrevious: () => void;
  handleNext: () => void;
}) {
  return (
    <div className="flex items-center text-sm space-x-0.5">
      <Hoverable
        icon={FiChevronLeft}
        onClick={currentPage === 1 ? undefined : handlePrevious}
      />

      <span className="text-text-darker select-none">
        {currentPage} / {totalPages}
      </span>

      <Hoverable
        icon={FiChevronRight}
        onClick={currentPage === totalPages ? undefined : handleNext}
      />
    </div>
  );
}
