import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { FiSearch } from "react-icons/fi";
import { OnyxDocument } from "@/lib/search/interfaces";
import { BaseQuestionIdentifier, SubQuestionDetail } from "../interfaces";
import { SourceChip2 } from "../input/ChatInputBar";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { openDocument } from "@/lib/search/utils";
import { SourcesDisplay } from "./SourcesDisplay";
import ReactMarkdown from "react-markdown";
import { MemoizedAnchor } from "./MemoizedTextComponents";
import { MemoizedParagraph } from "./MemoizedTextComponents";
import { extractCodeText, preprocessLaTeX } from "./codeUtils";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { CodeBlock } from "./CodeBlock";
import { CheckIcon, ChevronDown } from "lucide-react";
import { PHASE_MIN_MS, useStreamingMessages } from "./StreamingMessages";
import { CirclingArrowIcon } from "@/components/icons/icons";
import { handleCopy } from "./copyingUtils";
import { transformLinkUri } from "@/lib/utils";

export const StatusIndicator = ({ status }: { status: ToggleState }) => {
  return (
    <>
      {" "}
      {status != ToggleState.InProgress ? (
        <div
          className={` h-full w-full rounded-full z-10 
    bg-background border-3 border-background-900  "
    ${
      status === ToggleState.Todo
        ? "!border-[3px] border border-background-900 bg-background"
        : false
          ? "bg-background border-3 border border-background-900 rotating-border"
          : "bg-background-900 flex items-center  justify-center"
    } 
 `}
        >
          {status === ToggleState.Done && (
            <CheckIcon className="m-auto text-white" size={8} />
          )}
        </div>
      ) : (
        <div className="relative h-full w-full">
          <div className="absolute top-0 left-0 z-[100] h-full w-full rounded-full bg-background" />

          <CirclingArrowIcon
            size={12}
            className="absolute top-0 left-0 z-[2000] h-full w-full animate-spin"
          />
        </div>
      )}
    </>
  );
};

export interface TemporaryDisplay {
  question: string;
  tinyQuestion: string;
}
interface SubQuestionsDisplayProps {
  isStreamingQuestions: boolean;
  docSidebarToggled: boolean;
  finishedGenerating: boolean;
  currentlyOpenQuestion?: BaseQuestionIdentifier | null;
  subQuestions: SubQuestionDetail[];
  documents?: OnyxDocument[];
  toggleDocumentSelection: () => void;
  setPresentingDocument: (document: OnyxDocument) => void;
  unToggle: boolean;
  allowStreaming: () => void;
  secondLevelQuestions?: SubQuestionDetail[];
  showSecondLevel?: boolean;
  overallAnswerGenerating?: boolean;
  allowDocuments: () => void;
}

export enum ToggleState {
  Todo,
  InProgress,
  Done,
}

const SubQuestionDisplay: React.FC<{
  currentlyOpen: boolean;
  currentlyClosed: boolean;
  subQuestion: SubQuestionDetail | null;
  documents?: OnyxDocument[];
  isLast: boolean;
  unToggle: boolean;
  isFirst: boolean;
  setPresentingDocument: (document: OnyxDocument) => void;
  temporaryDisplay?: TemporaryDisplay;
  completed?: boolean;
  initialStatus: ToggleState;
  forcedStatus?: ToggleState;
}> = ({
  currentlyOpen,
  currentlyClosed,
  subQuestion,
  documents,
  isLast,
  unToggle,
  isFirst,
  temporaryDisplay,
  setPresentingDocument,
  completed,
  initialStatus,
  forcedStatus,
}) => {
  const [analysisToggled, setAnalysisToggled] = useState(false);
  const [status, setStatus] = useState(initialStatus);
  const [toggled, setToggled] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

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
      if (!lastMatch.endsWith("```")) {
        return preprocessLaTeX(content);
      }
    }
    content = content.replace(/\[([QD])(\d+)\]/g, (match, type, number) => {
      const citationNumber = parseInt(number, 10);
      return `[[${type}${citationNumber}]]()`;
    });

    content = content.replace(/\{\{(\d+)\}\}/g, (match, p1) => {
      const citationNumber = parseInt(p1, 10);
      return `[[${citationNumber}]]()`;
    });

    content = content.replace(/\]\](?!\()/g, "]]()");

    return (
      preprocessLaTeX(content) +
      (subQuestion?.answer_streaming ? " [*]() " : "")
    );
  };

  const finalContent =
    subQuestion && subQuestion.answer
      ? (processContent(subQuestion.answer as string) as string)
      : "";

  const paragraphCallback = useCallback(
    (props: any) => (
      <MemoizedParagraph fontSize={"sm"}>{props.children}</MemoizedParagraph>
    ),
    []
  );

  const anchorCallback = useCallback(
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={setPresentingDocument!}
        docs={subQuestion?.context_docs?.top_documents || documents}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
    [documents]
  );

  const textCallback = useCallback(
    (props: any) => (
      <span className="text-sm leading-tight">{props.children}</span>
    ),
    []
  );

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      code: ({ node, className, children }: any) => {
        const codeText = extractCodeText(
          node,
          subQuestion?.answer as string,
          children
        );

        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
      li: ({ children }: any) => (
        <li className="text-sm leading-tight">{children}</li>
      ),
      ul: ({ children }: any) => (
        <ul className="text-sm leading-tight pl-4 mt-0 mb-2">{children}</ul>
      ),
      ol: ({ children }: any) => (
        <ol className="text-sm leading-tight pl-4 mt-0 mb-2">{children}</ol>
      ),
    }),
    [anchorCallback, paragraphCallback, textCallback, subQuestion?.answer]
  );

  useEffect(() => {
    if (subQuestion?.is_complete) {
      setTimeout(() => setStatus(ToggleState.Done), PHASE_MIN_MS);
    }
  }, [subQuestion?.is_complete]);

  useEffect(() => {
    if (completed) {
      setTimeout(() => setStatus(ToggleState.Done), PHASE_MIN_MS);
      setIsVisible(true);
    }
  }, [completed]);

  useEffect(() => {
    if (unToggle) {
      if (subQuestion?.answer) {
        setTimeout(() => setStatus(ToggleState.Done), PHASE_MIN_MS);
      }
    } else {
      setStatus(ToggleState.InProgress);
    }
    setTimeout(
      () => {
        setToggled(!unToggle);
      },
      unToggle ? PHASE_MIN_MS * 0.75 : 0
    );
  }, [unToggle]);

  useEffect(() => {
    if (forcedStatus === ToggleState.Done) {
      setToggled(false);
    }
  }, [forcedStatus]);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (toggled && !temporaryDisplay) {
      setIsVisible(true);
    } else {
      timer = setTimeout(() => setIsVisible(false), 500);
    }
    return () => clearTimeout(timer);
  }, [toggled]);
  const questionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (currentlyOpen) {
      setToggled(true);
      setAnalysisToggled(true);
      if (questionRef.current) {
        setTimeout(() => {
          questionRef.current?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        }, 1000);
      }
    }
  }, [currentlyOpen]);

  useEffect(() => {
    if (currentlyClosed) {
      setTimeout(
        () => {
          setToggled(false);
        },
        temporaryDisplay ? 0 : 3000
      );
    }
  }, [currentlyClosed]);

  const analysisRef = useRef<HTMLDivElement>(null);
  const renderedMarkdown = useMemo(() => {
    return (
      <ReactMarkdown
        className="prose dark:prose-invert max-w-full text-base"
        components={markdownComponents}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        urlTransform={transformLinkUri}
      >
        {finalContent}
      </ReactMarkdown>
    );
  }, [finalContent, markdownComponents]);

  const memoizedDocs =
    subQuestion?.context_docs?.top_documents &&
    subQuestion?.context_docs?.top_documents.length > 0
      ? subQuestion?.context_docs?.top_documents
      : (documents || []).filter((doc) =>
          subQuestion?.context_docs?.top_documents?.some(
            (contextDoc) => contextDoc.document_id === doc.document_id
          )
        );

  return (
    <div className="relative">
      <div
        className={`absolute left-[5px] ${
          isFirst ? "top-[15px]" : "top-0"
        } bottom-0 w-[2px] bg-background-200

        ${isLast && !toggled ? "h-4" : "h-full"}`}
      />
      <div
        style={{ scrollMarginTop: "20px" }}
        ref={questionRef}
        className={`flex items-start ${!isLast ? "pb-2" : ""}`}
      >
        <div className="absolute left-0 w-3 h-3 rounded-full mt-[12px] z-10">
          <StatusIndicator status={forcedStatus || status} />
        </div>
        <div className="ml-8 w-full">
          <div
            className="flex -mx-2 rounded-md px-2 hover:bg-background-100 dark:hover:bg-neutral-800 items-start py-1.5 my-.5 cursor-pointer"
            onClick={() => setToggled(!toggled)}
          >
            <div className="text-black text-base font-medium leading-normal flex-grow pr-2">
              {subQuestion?.question || temporaryDisplay?.question}
            </div>
            <ChevronDown
              className={`mt-0.5 flex-none text-text-darker transition-transform duration-500 ease-in-out ${
                toggled ? "" : "-rotate-90"
              }`}
              size={20}
            />
          </div>

          {!temporaryDisplay && (
            <div
              className={`transition-all duration-300 ease-in-out ${
                toggled ? "max-h-[1000px]" : "max-h-0"
              }`}
            >
              {isVisible && subQuestion && (
                <div
                  className={`transform transition-all duration-300 ease-in-out origin-top ${
                    toggled ? "scale-y-100 opacity-100" : "scale-y-95 opacity-0"
                  }`}
                >
                  <div className="pl-0 pb-2">
                    <div className="mb-4 flex flex-col gap-2">
                      <div className="text-text-800 text-xs font-medium leading-normal">
                        Searching
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {subQuestion?.sub_queries?.map((query, queryIndex) => (
                          <SourceChip2
                            key={queryIndex}
                            icon={<FiSearch size={10} />}
                            title={query.query}
                            includeTooltip
                          />
                        ))}
                      </div>
                    </div>

                    {(subQuestion?.is_complete || memoizedDocs?.length > 0) && (
                      <div className="mb-4 flex flex-col gap-2">
                        <div className="text-text-800 text-xs font-medium leading-normal">
                          Reading
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {memoizedDocs.length > 0 ? (
                            memoizedDocs.slice(0, 10).map((doc, docIndex) => {
                              const truncatedIdentifier =
                                doc.semantic_identifier?.slice(0, 20) || "";
                              return (
                                <SourceChip2
                                  includeAnimation
                                  onClick={() =>
                                    openDocument(doc, setPresentingDocument)
                                  }
                                  key={docIndex}
                                  icon={<ResultIcon doc={doc} size={10} />}
                                  title={`${truncatedIdentifier}${
                                    truncatedIdentifier.length === 20
                                      ? "..."
                                      : ""
                                  }`}
                                />
                              );
                            })
                          ) : (
                            <div className="text-black text-sm font-medium">
                              No sources found
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {(subQuestion?.is_complete ||
                      subQuestion?.answer?.length > 0) && (
                      <div className="flex flex-col gap-2">
                        <div
                          className="text-text-800 cursor-pointer items-center text-xs flex gap-x-1 font-medium leading-normal"
                          onClick={() => setAnalysisToggled(!analysisToggled)}
                        >
                          Analyzing
                          <ChevronDown
                            className={`transition-transform duration-200 ${
                              analysisToggled ? "" : "-rotate-90"
                            }`}
                            size={8}
                          />
                        </div>
                        {analysisToggled && (
                          <div
                            ref={analysisRef}
                            onCopy={(e) => handleCopy(e, analysisRef)}
                            className="flex flex-wrap gap-2"
                          >
                            {renderedMarkdown}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
          {temporaryDisplay &&
            ((status === ToggleState.InProgress &&
              forcedStatus !== ToggleState.Done) ||
              toggled) && (
              <div
                className={`transform ease-in-out origin-top ${
                  toggled ? "scale-y-100 opacity-100" : "scale-y-100 opacity-0"
                }`}
              >
                <div className="pl-0">
                  <div className="flex flex-col gap-2">
                    <div className="leading-none text-text-800 text-xs font-medium">
                      {temporaryDisplay?.tinyQuestion}
                    </div>
                  </div>
                </div>
              </div>
            )}
        </div>
      </div>
    </div>
  );
};

const SubQuestionsDisplay: React.FC<SubQuestionsDisplayProps> = ({
  isStreamingQuestions,
  finishedGenerating,
  subQuestions,
  allowStreaming,
  currentlyOpenQuestion,
  documents,
  toggleDocumentSelection,
  setPresentingDocument,
  secondLevelQuestions,
  docSidebarToggled,
  showSecondLevel,
  overallAnswerGenerating,
  allowDocuments,
}) => {
  const [showSummarizing, setShowSummarizing] = useState(
    finishedGenerating && !overallAnswerGenerating
  );
  const [initiallyFinishedGenerating, setInitiallyFinishedGenerating] =
    useState(finishedGenerating);
  // const []
  const { dynamicSubQuestions } = useStreamingMessages(
    subQuestions,
    () => {},
    () => {
      setShowSummarizing(true);
    },
    isStreamingQuestions
  );
  const { dynamicSubQuestions: dynamicSecondLevelQuestions } =
    useStreamingMessages(
      secondLevelQuestions || [],
      () => {},
      () => {},
      false
    );

  const memoizedSubQuestions = useMemo(() => {
    return initiallyFinishedGenerating ? subQuestions : dynamicSubQuestions;
  }, [initiallyFinishedGenerating, dynamicSubQuestions, subQuestions]);

  const memoizedSecondLevelQuestions = useMemo(() => {
    return overallAnswerGenerating
      ? dynamicSecondLevelQuestions
      : secondLevelQuestions;
  }, [
    overallAnswerGenerating,
    dynamicSecondLevelQuestions,
    secondLevelQuestions,
  ]);

  const pendingSubqueries =
    subQuestions.filter(
      (subQuestion) => (subQuestion?.sub_queries || [])?.length > 0
    ).length == 0;

  const [streamedText, setStreamedText] = useState(
    finishedGenerating ? "Summarize findings" : ""
  );
  const [canShowSummarizing, setCanShowSummarizing] =
    useState(finishedGenerating);

  const [shownDocuments, setShownDocuments] = useState(documents);

  useEffect(() => {
    if (canShowSummarizing && documents && documents.length > 0) {
      setTimeout(
        () => {
          setShownDocuments(documents);
        },
        finishedGenerating ? 0 : 800
      );
    }
  }, [documents, canShowSummarizing]);

  useEffect(() => {
    if (
      memoizedSubQuestions.length > 0 &&
      memoizedSubQuestions.filter(
        (subQuestion) => subQuestion?.answer.length > 2
      ).length == subQuestions.length
    ) {
      setTimeout(() => {
        setCanShowSummarizing(true);
      }, PHASE_MIN_MS);
      setTimeout(() => {
        allowDocuments();
      }, PHASE_MIN_MS * 2);
    }
  }, [memoizedSubQuestions]);

  useEffect(() => {
    if (showSummarizing && streamedText !== "Summarize findings") {
      const fullText = "Summarize findings";
      let index = 0;

      const streamInterval = setInterval(() => {
        if (index <= fullText.length) {
          setStreamedText(fullText.slice(0, index));
          index++;
          if (index === fullText.length) {
            allowDocuments();
          }
        } else {
          clearInterval(streamInterval);
        }
      }, 10);
    }
  }, [showSummarizing]);

  useEffect(() => {
    if (shownDocuments && shownDocuments.length > 0) {
      setTimeout(() => {
        allowStreaming();
      }, 1500);
    }
  }, [shownDocuments]);

  return (
    <div className="-mt-2 w-full">
      <style jsx global>{`
        @keyframes rotate {
          0% {
            transform: rotate(0deg);
          }
          100% {
            transform: rotate(360deg);
          }
        }
        .rotating-circle::before {
          content: "";
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          border: 2px solid transparent;
          border-top-color: #ffffff;
          border-radius: 50%;
          animation: rotate 1s linear infinite;
        }
        .rotating-border {
          position: relative;
          display: inline-block;
        }

        .rotating-border::after {
          content: "";
          position: absolute;
          top: -2px;
          left: -2px;
          right: -2px;
          bottom: -2px;
          border: 2px solid transparent;
          border-top-color: #aaa;
          border-radius: 50%;
          animation: rotateArc 1s linear infinite;
          pointer-events: none;
        }

        @keyframes rotateArc {
          0% {
            transform: rotate(0deg);
          }
          100% {
            transform: rotate(360deg);
          }
        }
      `}</style>
      <div className="relative">
        {memoizedSubQuestions.map((subQuestion, index) => (
          <SubQuestionDisplay
            currentlyOpen={
              currentlyOpenQuestion?.level === subQuestion.level &&
              currentlyOpenQuestion?.level_question_num ===
                subQuestion.level_question_num
            }
            currentlyClosed={
              currentlyOpenQuestion != null &&
              currentlyOpenQuestion != undefined &&
              !(
                currentlyOpenQuestion.level === subQuestion.level &&
                currentlyOpenQuestion.level_question_num ===
                  subQuestion.level_question_num
              )
            }
            key={index}
            subQuestion={subQuestion}
            initialStatus={
              !finishedGenerating ? ToggleState.Todo : ToggleState.Done
            }
            documents={documents}
            isLast={
              !showSummarizing &&
              memoizedSubQuestions.length == index + 1 &&
              !(
                showSecondLevel &&
                memoizedSecondLevelQuestions &&
                memoizedSecondLevelQuestions?.length > 0
              )
            }
            isFirst={index === 0}
            setPresentingDocument={setPresentingDocument}
            unToggle={
              subQuestion?.sub_queries == undefined ||
              subQuestion?.sub_queries.length == 0 ||
              (subQuestion?.sub_queries?.length > 0 &&
                (subQuestion.answer == undefined ||
                  subQuestion.answer.length > 3))
            }
          />
        ))}
        {showSecondLevel &&
          memoizedSecondLevelQuestions &&
          memoizedSecondLevelQuestions?.map((subQuestion, index) => (
            <SubQuestionDisplay
              initialStatus={
                !finishedGenerating ? ToggleState.Todo : ToggleState.Done
              }
              currentlyOpen={
                currentlyOpenQuestion?.level === subQuestion.level &&
                currentlyOpenQuestion?.level_question_num ===
                  subQuestion.level_question_num
              }
              currentlyClosed={
                currentlyOpenQuestion != null &&
                currentlyOpenQuestion != undefined &&
                !(
                  currentlyOpenQuestion.level === subQuestion.level &&
                  currentlyOpenQuestion.level_question_num ===
                    subQuestion.level_question_num
                )
              }
              key={index}
              subQuestion={subQuestion}
              documents={documents}
              isLast={
                !showSummarizing &&
                memoizedSecondLevelQuestions.length == index + 1
              }
              isFirst={false}
              setPresentingDocument={setPresentingDocument}
              unToggle={
                subQuestion?.sub_queries == undefined ||
                subQuestion?.sub_queries.length == 0 ||
                (subQuestion?.sub_queries?.length > 0 &&
                  (subQuestion.answer == undefined ||
                    subQuestion.answer.length > 3))
              }
            />
          ))}

        {showSummarizing && (
          <SubQuestionDisplay
            initialStatus={
              !finishedGenerating ? ToggleState.Todo : ToggleState.Done
            }
            currentlyOpen={false}
            currentlyClosed={
              shownDocuments != null && shownDocuments.length > 0
            }
            forcedStatus={
              shownDocuments && shownDocuments.length > 0
                ? ToggleState.Done
                : undefined
            }
            subQuestion={null}
            documents={shownDocuments}
            isLast={true}
            isFirst={false}
            setPresentingDocument={setPresentingDocument}
            unToggle={!canShowSummarizing || finishedGenerating!}
            completed={shownDocuments && shownDocuments.length > 0}
            temporaryDisplay={{
              question: streamedText,
              tinyQuestion: "Combining results",
            }}
          />
        )}

        {/* If we have no subqueries, but have subquestions, show the "thinking" */}
        {/* If we have subAnswers, but no overall answer, show hte otehr thinking */}
      </div>

      {shownDocuments && shownDocuments.length > 0 && (
        <SourcesDisplay
          setPresentingDocument={setPresentingDocument}
          docSidebarToggled={docSidebarToggled}
          hideDocumentDisplay
          animateEntrance={true}
          toggleDocumentSelection={toggleDocumentSelection}
          documents={shownDocuments}
          threeCols={true}
        />
      )}
    </div>
  );
};

export default SubQuestionsDisplay;
