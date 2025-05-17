import { useState, useRef, useEffect } from "react";
import { SubQuestionDetail } from "../interfaces";

export enum StreamingPhase {
  WAITING = "waiting",
  SUB_QUERIES = "sub_queries",
  CONTEXT_DOCS = "context_docs",
  ANSWER = "answer",
  EVALUATE = "evaluate",
  COMPLETE = "complete",
  COMPARE = "compare",
}

export const StreamingPhaseText: Record<StreamingPhase, string> = {
  [StreamingPhase.WAITING]: "Extracting key concepts",
  [StreamingPhase.SUB_QUERIES]: "Identifying additional questions",
  [StreamingPhase.CONTEXT_DOCS]: "Reading more documents",
  [StreamingPhase.EVALUATE]: "Evaluating new context",
  [StreamingPhase.ANSWER]: "Generating refined answer",
  [StreamingPhase.COMPARE]: "Comparing results",
  [StreamingPhase.COMPLETE]: "Finished",
};

export const PHASES_ORDER: StreamingPhase[] = [
  StreamingPhase.WAITING,
  StreamingPhase.SUB_QUERIES,
  StreamingPhase.CONTEXT_DOCS,
  StreamingPhase.EVALUATE,
  StreamingPhase.ANSWER,
  StreamingPhase.COMPARE,
  StreamingPhase.COMPLETE,
];

interface SubQuestionProgress {
  questionDone: boolean;
  questionCharIndex: number;
  currentPhase: StreamingPhase;
  // Track when we started this phase
  phaseStartTime: number;
  waitingTimeoutSet: boolean;
  subQueryIndex: number;
  subQueryCharIndex: number;
  docIndex: number;
  lastDocTimestamp: number | null;
  answerCharIndex: number;
}

export const PHASE_MIN_MS = 800; // Minimum phase duration in ms

function canTransition(p: SubQuestionProgress) {
  return Date.now() - p.phaseStartTime >= PHASE_MIN_MS;
}

const DOC_DELAY_MS = 100;

export const useStreamingMessages = (
  subQuestions: SubQuestionDetail[],
  allowStreaming: () => void,
  onComplete: () => void,
  isStreamingQuestions: boolean
) => {
  const [dynamicSubQuestions, setDynamicSubQuestions] = useState<
    SubQuestionDetail[]
  >([]);

  const isStreamingQuestionsRef = useRef(isStreamingQuestions);

  useEffect(() => {
    isStreamingQuestionsRef.current = isStreamingQuestions;
  }, [isStreamingQuestions]);

  const subQuestionsRef = useRef<SubQuestionDetail[]>(subQuestions);
  useEffect(() => {
    subQuestionsRef.current = subQuestions;
  }, [subQuestions]);

  const dynamicSubQuestionsRef = useRef<SubQuestionDetail[]>([]);

  const progressRef = useRef<SubQuestionProgress[]>([]);

  useEffect(() => {
    subQuestions.forEach((sq, i) => {
      if (!progressRef.current[i]) {
        progressRef.current[i] = {
          questionDone: false,
          questionCharIndex: 0,
          waitingTimeoutSet: false,
          // Start subQ #0 in SUB_QUERIES immediately, others in WAITING
          currentPhase: StreamingPhase.WAITING,
          // i === 0 ? StreamingPhase.SUB_QUERIES : StreamingPhase.WAITING,
          // We set the phase start time right away
          phaseStartTime: Date.now(),
          subQueryIndex: 0,
          subQueryCharIndex: 0,
          docIndex: 0,
          lastDocTimestamp: null,
          answerCharIndex: 0,
        };
      }

      if (!dynamicSubQuestionsRef.current[i]) {
        dynamicSubQuestionsRef.current[i] = {
          level: sq.level,
          level_question_num: sq.level_question_num,
          question: "",
          answer: "",
          sub_queries: [],
          context_docs: { top_documents: [] },
        };
      }
    });

    setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);
  }, [subQuestions]);

  useEffect(() => {
    let stop = false;

    function loadNextPiece() {
      if (stop) return;

      const actualSubQs = subQuestionsRef.current;
      if (!actualSubQs || actualSubQs.length === 0) {
        setTimeout(loadNextPiece, 100);
        return;
      }

      // Stream high-level questions sequentially
      let didStreamQuestion = false;
      let allQuestionsComplete = true;

      for (let i = 0; i < actualSubQs.length; i++) {
        const sq = actualSubQs[i];
        if (sq === undefined) {
          continue;
        }

        const p = progressRef.current[i];
        if (p === undefined) {
          continue;
        }

        const dynSQ = dynamicSubQuestionsRef.current[i];
        if (dynSQ === undefined) {
          continue;
        }

        if (i < 0) {
          continue;
        }

        if (i > 0) {
          const p2 = progressRef.current[i - 1];
          if (p2 === undefined) {
            continue;
          }

          if (!p2.questionDone) {
            continue;
          }
        }

        // Always stream the first subquestion (index 0)
        // For others, only stream if the previous question is complete
        if (sq.question) {
          const nextIndex = p.questionCharIndex + 1;
          if (nextIndex <= sq.question.length) {
            dynSQ.question = sq.question.slice(0, nextIndex);
            p.questionCharIndex = nextIndex;
            if (nextIndex >= sq.question.length && sq.is_stopped) {
              p.questionDone = true;
            }
            didStreamQuestion = true;
            allQuestionsComplete = false;

            // Break after streaming one question to ensure sequential behavior
            break;
          }
        }

        if (!p.questionDone) {
          allQuestionsComplete = false;
        }
      }

      if (
        allQuestionsComplete &&
        !didStreamQuestion &&
        !isStreamingQuestionsRef.current
      ) {
        onComplete();
      }

      if (didStreamQuestion) {
        setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);
        setTimeout(loadNextPiece, 2);
        return;
      }

      // 2) Handle SUB_QUERIES → CONTEXT_DOCS → ANSWER → COMPLETE
      for (let i = 0; i < actualSubQs.length; i++) {
        const sq = actualSubQs[i];
        if (sq === undefined) {
          continue;
        }

        const dynSQ = dynamicSubQuestionsRef.current[i];
        if (dynSQ === undefined) {
          continue;
        }

        dynSQ.answer_streaming = sq.answer_streaming;

        const p = progressRef.current[i];
        if (p === undefined) {
          continue;
        }

        // Wait for subquestion #0 or the previous subquestion's progress
        if (p.currentPhase === StreamingPhase.WAITING) {
          if (i === 0) {
            // subquestion #0 can move on if 300ms has passed in WAITING (though it starts in SUB_QUERIES by default)
            if (canTransition(p)) {
              p.currentPhase = StreamingPhase.SUB_QUERIES;
              p.phaseStartTime = Date.now();
            }
          } else {
            const prevP = progressRef.current[i - 1];
            if (
              prevP !== undefined &&
              (prevP.currentPhase === StreamingPhase.ANSWER ||
                prevP.currentPhase === StreamingPhase.COMPLETE)
            ) {
              // Can only proceed if we've spent enough time in WAITING
              if (canTransition(p) && !p.waitingTimeoutSet) {
                p.waitingTimeoutSet = true;
                setTimeout(() => {
                  p.currentPhase = StreamingPhase.SUB_QUERIES;
                  p.phaseStartTime = Date.now();
                }, PHASE_MIN_MS);
              }
            }
          }
        }

        switch (p.currentPhase) {
          case StreamingPhase.SUB_QUERIES: {
            const subQueries = sq.sub_queries || [];
            const docs = sq.context_docs?.top_documents || [];
            const hasDocs = docs.length > 0;
            const hasAnswer = !!sq.answer?.length;

            // "Stream" the subqueries (in this code, it just sets them all at once)
            while (dynSQ.sub_queries!.length < subQueries.length) {
              const subquery_detail = subQueries[0];
              if (subquery_detail === undefined) {
                continue;
              }

              const subquery_id = subquery_detail.query_id;
              dynSQ.sub_queries!.push({
                query: "",
                query_id: subquery_id,
              });
            }

            for (let j = 0; j < subQueries.length; j++) {
              const dyn_subquery_detail = dynSQ.sub_queries![j];
              if (dyn_subquery_detail === undefined) {
                continue;
              }

              const subquery_detail = subQueries[j];
              if (subquery_detail === undefined) {
                continue;
              }

              if (
                dyn_subquery_detail.query.length < subquery_detail.query.length
              ) {
                dyn_subquery_detail.query = subquery_detail.query;
              } else {
                // console.log("NOT STREAMING");
              }
            }
            // console.log(subQueries);

            // If we've "done" subqueries and see docs or an answer, move on — but only if 300ms have passed
            if (hasDocs || hasAnswer) {
              if (canTransition(p)) {
                p.currentPhase = StreamingPhase.CONTEXT_DOCS;
                p.phaseStartTime = Date.now();
                p.lastDocTimestamp = null;
              }
            }
            break;
          }

          case StreamingPhase.CONTEXT_DOCS: {
            const docs = sq.context_docs?.top_documents || [];
            const hasAnswer = !!sq.answer?.length;

            // If we see an answer but no docs, jump to ANSWER
            if (hasAnswer && docs.length === 0) {
              if (canTransition(p)) {
                p.currentPhase = StreamingPhase.ANSWER;
                p.phaseStartTime = Date.now();
              }
              break;
            }

            // Add all docs at once (same as original)
            if (p.docIndex < docs.length) {
              docs.forEach((docToAdd) => {
                const alreadyAdded = dynSQ.context_docs?.top_documents.some(
                  (d) => d.document_id === docToAdd.document_id
                );
                if (!alreadyAdded) {
                  dynSQ.context_docs?.top_documents.push(docToAdd);
                }
              });
              p.docIndex = docs.length;
              p.lastDocTimestamp = Date.now();
            }

            if (hasAnswer) {
              // Once we've added all docs and see an answer, move on *after* 300ms
              if (canTransition(p)) {
                p.currentPhase = StreamingPhase.ANSWER;
                p.phaseStartTime = Date.now();
              }
            }
            break;
          }

          case StreamingPhase.ANSWER: {
            const answerText = sq.answer || "";
            const remainingChars = answerText.length - p.answerCharIndex;
            const charsToStream = Math.min(remainingChars, 10);

            if (charsToStream > 0) {
              const nextIndex = p.answerCharIndex + charsToStream;
              dynSQ.answer = answerText.slice(0, nextIndex);
              p.answerCharIndex = nextIndex;

              // If we've streamed everything and it's "complete"
              if (nextIndex >= answerText.length && sq.is_complete) {
                // Only move to COMPLETE if 300ms has passed in ANSWER
                if (canTransition(p)) {
                  dynSQ.is_complete = true;
                  p.currentPhase = StreamingPhase.COMPLETE;
                  p.phaseStartTime = Date.now();
                  console.log("ANSWER COMPLETE");

                  // Check if this is the last subquestion at level 0
                  if (
                    sq.level === 0 &&
                    sq.level_question_num ===
                      Math.max(
                        ...subQuestions
                          .filter((q) => q.level === 0)
                          .map((q) => q.level_question_num)
                      )
                  ) {
                    console.log("ALLOW STREAMING");
                    allowStreaming();
                  } else {
                    console.log("DO NOT ALLOW STREAMING");
                  }
                }
              }
            }
            break;
          }

          case StreamingPhase.COMPLETE:
          case StreamingPhase.WAITING:
          default:
            break;
        }
      }

      setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);
      setTimeout(loadNextPiece, 2);
    }

    loadNextPiece();

    return () => {
      stop = true;
    };
  }, []);

  return { dynamicSubQuestions };
};
