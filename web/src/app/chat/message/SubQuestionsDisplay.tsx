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
import { ResultIcon } from "@/components/chat_search/sources/SourceCard";
import { openDocument } from "@/lib/search/utils";
import { SourcesDisplay } from "./SourcesDisplay";
import ReactMarkdown from "react-markdown";
import { MemoizedAnchor } from "./MemoizedTextComponents";
import { MemoizedParagraph } from "./MemoizedTextComponents";
import { extractCodeText, preprocessLaTeX } from "./codeUtils";

import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "./CodeBlock";
import { ChevronDown } from "lucide-react";
import { PHASE_MIN_MS, useStreamingMessages } from "./StreamingMessages";

export interface TemporaryDisplay {
  question: string;
  tinyQuestion: string;
}
interface SubQuestionsDisplayProps {
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
}) => {
  const [analysisToggled, setAnalysisToggled] = useState(false);
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
    // Add newlines after ]] or ) if there's text immediately following
    content = content.replace(/(\]\]|\))((?!\s|\n|\[|\(|$).)/g, "$1\n$2");
    // Turn {{number}} into citation in content
    content = content.replace(/\{\{(\d+)\}\}/g, (match, p1) => {
      const citationNumber = parseInt(p1, 10);
      return `[[${citationNumber}]]()`;
    });

    // Add () after ]] if not present
    content = content.replace(/\]\](?!\()/g, "]]()");

    // // Turn [Qn] into citation in content
    // content = content.replace(/\[Q(\d+)\]/g, (match, p1) => {
    //   const questionNumber = parseInt(p1, 10);
    //   return `[[Q${questionNumber}]]()`;
    // });

    return (
      preprocessLaTeX(content) + (!subQuestion?.is_complete ? " [*]() " : "")
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
    setTimeout(
      () => {
        setToggled(!unToggle);
      },
      unToggle ? PHASE_MIN_MS : 0
    );
  }, [unToggle]);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (toggled) {
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
      console.log("TOGGLE");
      setTimeout(() => {
        setToggled(false);
      }, 3000);
    }
  }, [currentlyClosed]);

  const renderedMarkdown = useMemo(() => {
    return (
      <ReactMarkdown
        className="prose max-w-full text-base"
        components={markdownComponents}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
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
    <div className="bg- relative">
      <div
        className={`absolute left-[5px] ${
          isFirst ? "top-[9px]" : "top-0"
        } bottom-0 w-[2px]  bg-neutral-200

        ${isLast && !toggled ? "h-4" : "h-full"}`}
      />
      <div
        style={{ scrollMarginTop: "20px" }}
        ref={questionRef}
        className="flex items-start pb-4"
      >
        <div
          className={`absolute left-0 w-3 h-3 rounded-full mt-[9px] z-10 ${
            subQuestion?.answer || (temporaryDisplay && completed)
              ? "bg-neutral-700"
              : "bg-neutral-700 rotating-circle"
          }`}
        />
        <div className="ml-8 w-full">
          <div
            className="flex items-start py-1 cursor-pointer"
            onClick={() => setToggled(!toggled)}
          >
            <div className="text-black text-base font-medium leading-normal flex-grow pr-2">
              {subQuestion?.question || temporaryDisplay?.question}
            </div>
            <ChevronDown
              className={`mt-0.5 text-text-darker transition-transform duration-500 ease-in-out ${
                toggled ? "rotate-180" : ""
              }`}
              size={20}
            />
          </div>
          <div
            className={`transition-all duration-100 ease-in-out ${
              toggled ? "max-h-[1000px]" : "max-h-0"
            }`}
          >
            {isVisible && (
              <div
                className={`transform transition-all duration-100 ease-in-out origin-top ${
                  toggled ? "scale-y-100 opacity-100" : "scale-y-95 opacity-0"
                }`}
              >
                {subQuestion ? (
                  <div className="pl-0 pb-2">
                    <div className="mb-4 flex flex-col gap-2">
                      <div className="text-[#4a4a4a] text-xs font-medium leading-normal">
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
                        <div className="text-[#4a4a4a] text-xs font-medium leading-normal">
                          Reading
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {memoizedDocs.slice(0, 10).map((doc, docIndex) => {
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
                                  truncatedIdentifier.length === 20 ? "..." : ""
                                }`}
                              />
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {(subQuestion?.is_complete ||
                      subQuestion?.answer?.length > 0) && (
                      <div className="flex flex-col gap-2">
                        <div
                          className="text-[#4a4a4a] cursor-pointer items-center text-xs flex gap-x-1 font-medium leading-normal"
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
                          <div className="flex flex-wrap gap-2">
                            {renderedMarkdown}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="pl-0">
                    <div className="flex flex-col gap-2">
                      <div className="text-[#4a4a4a] text-xs font-medium leading-normal">
                        {temporaryDisplay?.tinyQuestion}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

const SubQuestionsDisplay: React.FC<SubQuestionsDisplayProps> = ({
  subQuestions,
  allowStreaming,
  currentlyOpenQuestion,
  documents,
  toggleDocumentSelection,
  setPresentingDocument,
  secondLevelQuestions,
  showSecondLevel,
  overallAnswerGenerating,
}) => {
  const { dynamicSubQuestions } = useStreamingMessages(subQuestions, () => {});
  const { dynamicSubQuestions: dynamicSecondLevelQuestions } =
    useStreamingMessages(secondLevelQuestions || [], () => {});
  const memoizedSubQuestions = useMemo(() => {
    return true ? dynamicSubQuestions : subQuestions;
  }, [overallAnswerGenerating, dynamicSubQuestions, subQuestions]);

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

  const overallAnswer =
    memoizedSubQuestions.length > 0 &&
    memoizedSubQuestions.filter(
      (subQuestion) => subQuestion?.answer.length > 10
    ).length == memoizedSubQuestions.length;

  useEffect(() => {
    if (overallAnswer) {
      allowStreaming();
    }
  }, [overallAnswer]);

  return (
    <div className="w-full">
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
      `}</style>
      <div className="relative">
        {/* {subQuestions.map((subQuestion, index) => ( */}
        {memoizedSubQuestions.map((subQuestion, index) => (
          // {dynamicSubQuestions.map((subQuestion, index) => (
          <SubQuestionDisplay
            currentlyOpen={
              currentlyOpenQuestion?.level === subQuestion.level &&
              currentlyOpenQuestion?.level_question_nr ===
                subQuestion.level_question_nr
            }
            currentlyClosed={
              currentlyOpenQuestion != null &&
              currentlyOpenQuestion != undefined &&
              !(
                currentlyOpenQuestion.level === subQuestion.level &&
                currentlyOpenQuestion.level_question_nr ===
                  subQuestion.level_question_nr
              )
            }
            key={index}
            subQuestion={subQuestion}
            documents={documents}
            isLast={
              index === subQuestions.length - 1 &&
              !(showSecondLevel && memoizedSecondLevelQuestions) &&
              !overallAnswer
            }
            isFirst={index === 0}
            setPresentingDocument={setPresentingDocument}
            unToggle={
              subQuestion?.sub_queries == undefined ||
              subQuestion?.sub_queries.length == 0 ||
              (subQuestion?.sub_queries?.length > 0 &&
                (subQuestion.answer == undefined ||
                  subQuestion.answer.length > 3))
              //   subQuestion == undefined &&
              //   subQuestion.answer != undefined &&
              //   !(
              //     dynamicSubQuestions[index + 1] != undefined ||
              //     dynamicSubQuestions[index + 1]?.sub_queries?.length! > 0
              //   )
            }
          />
        ))}
        {showSecondLevel &&
          memoizedSecondLevelQuestions &&
          memoizedSecondLevelQuestions?.map((subQuestion, index) => (
            <SubQuestionDisplay
              currentlyOpen={
                currentlyOpenQuestion?.level === subQuestion.level &&
                currentlyOpenQuestion?.level_question_nr ===
                  subQuestion.level_question_nr
              }
              currentlyClosed={
                currentlyOpenQuestion != null &&
                currentlyOpenQuestion != undefined &&
                !(
                  currentlyOpenQuestion.level === subQuestion.level &&
                  currentlyOpenQuestion.level_question_nr ===
                    subQuestion.level_question_nr
                )
              }
              key={index}
              subQuestion={subQuestion}
              documents={documents}
              isLast={
                index === memoizedSecondLevelQuestions.length - 1 &&
                !overallAnswer
              }
              isFirst={false}
              setPresentingDocument={setPresentingDocument}
              unToggle={
                subQuestion?.sub_queries == undefined ||
                subQuestion?.sub_queries.length == 0 ||
                (subQuestion?.sub_queries?.length > 0 &&
                  (subQuestion.answer == undefined ||
                    subQuestion.answer.length > 3))
                //   subQuestion == undefined &&
                //   subQuestion.answer != undefined &&
                //   !(
                //     dynamicSubQuestions[index + 1] != undefined ||
                //     dynamicSubQuestions[index + 1]?.sub_queries?.length! > 0
                //   )
              }
            />
          ))}

        {false ? (
          <></>
        ) : // <SubQuestionDisplay
        //   currentlyOpen={false}
        //   currentlyClosed={false}
        //   subQuestion={null}
        //   documents={documents}
        //   isLast={false}
        //   isFirst={false}
        //   setPresentingDocument={setPresentingDocument}
        //   unToggle={false}
        //   temporaryDisplay={{
        //     question: "Plotting",
        //     tinyQuestion: "Plotting next step",
        //   }}
        // />
        overallAnswer ? (
          <SubQuestionDisplay
            currentlyOpen={false}
            currentlyClosed={false}
            subQuestion={null}
            documents={documents}
            isLast={false}
            isFirst={false}
            setPresentingDocument={setPresentingDocument}
            unToggle={!overallAnswerGenerating}
            completed={!overallAnswerGenerating}
            temporaryDisplay={{
              question: "Summarizing findings",
              tinyQuestion: "Combining results",
            }}
          />
        ) : null}
        {/* {overallAnswerGenerating ? "not complete" : "complete"} */}
        {/* If we have no subqueries, but have subquestions, show the "thinking" */}
        {/* If we have subAnswers, but no overall answer, show hte otehr thinking */}
      </div>

      {documents && documents.length > 0 && (
        <SourcesDisplay
          animateEntrance={true}
          toggleDocumentSelection={toggleDocumentSelection}
          documents={documents}
        />
      )}
    </div>
  );
};

export default SubQuestionsDisplay;
