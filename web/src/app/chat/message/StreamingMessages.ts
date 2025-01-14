import { useState, useRef, useEffect } from "react";
import { SubQuestionDetail } from "../interfaces";

enum SubQStreamingPhase {
  WAITING = "waiting",
  SUB_QUERIES = "sub_queries",
  CONTEXT_DOCS = "context_docs",
  ANSWER = "answer",
  COMPLETE = "complete",
}

interface SubQuestionProgress {
  // Tracks if we're done with the question
  questionDone: boolean;
  // How far we've gotten in the question
  questionCharIndex: number;
  // What we're currently streaming
  currentPhase: SubQStreamingPhase;
  // For sub-queries
  subQueryIndex: number; // which one we're on
  subQueryCharIndex: number; // how much we've typed
  // For docs
  docIndex: number; // how many we've shown
  /** Time (ms) we last added a doc for this subquestion */
  lastDocTimestamp: number | null;
  // For the answer
  answerCharIndex: number; // how much we've typed
}

const DOC_DELAY_MS = 100;

export const useStreamingMessages = (
  subQuestions: SubQuestionDetail[],
  allowStreaming: () => void
) => {
  // What we show to the user
  const [dynamicSubQuestions, setDynamicSubQuestions] = useState<
    SubQuestionDetail[]
  >([]);

  // Keep the latest subQuestions handy
  const subQuestionsRef = useRef<SubQuestionDetail[]>(subQuestions);
  useEffect(() => {
    subQuestionsRef.current = subQuestions;
  }, [subQuestions]);

  // Our working copy
  const dynamicSubQuestionsRef = useRef<SubQuestionDetail[]>([]);

  // Track progress for each subquestion
  const progressRef = useRef<SubQuestionProgress[]>([]);

  // Set up progress tracking without resetting existing progress
  useEffect(() => {
    subQuestions.forEach((sq, i) => {
      if (!progressRef.current[i]) {
        // New progress object
        progressRef.current[i] = {
          questionDone: false,
          questionCharIndex: 0,
          // First one starts right away, others wait
          currentPhase:
            i === 0
              ? SubQStreamingPhase.SUB_QUERIES
              : SubQStreamingPhase.WAITING,
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
          level_question_nr: sq.level_question_nr,
          question: "",
          answer: "",
          sub_queries: [],
          context_docs: { top_documents: [] },
        };
      }
    });

    // Force update to show new empty slots
    setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);
  }, [subQuestions]);

  // Main streaming loop
  useEffect(() => {
    let stop = false; // for cleanup

    function loadNextPiece() {
      if (stop) return;

      const actualSubQs = subQuestionsRef.current;
      if (!actualSubQs || actualSubQs.length === 0) {
        // No data yet, check again soon
        setTimeout(loadNextPiece, 100);
        return;
      }

      // Stream questions first
      let didStreamQuestion = false;
      for (let i = 0; i < actualSubQs.length; i++) {
        const sq = actualSubQs[i];
        const p = progressRef.current[i];
        const dynSQ = dynamicSubQuestionsRef.current[i];

        // Stream one more char if needed
        if (!p.questionDone && sq.question) {
          const nextIndex = p.questionCharIndex + 1;
          dynSQ.question = sq.question.slice(0, nextIndex);
          p.questionCharIndex = nextIndex;

          if (nextIndex >= sq.question.length) {
            p.questionDone = true;
          }
          didStreamQuestion = true;
        }
      }

      if (didStreamQuestion) {
        setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);
        setTimeout(loadNextPiece, 15);
        return;
      }

      // Now handle each subquestion
      for (let i = 0; i < actualSubQs.length; i++) {
        const sq = actualSubQs[i];
        const dynSQ = dynamicSubQuestionsRef.current[i];
        const p = progressRef.current[i];

        // Start streaming when it's our turn
        if (p.currentPhase === SubQStreamingPhase.WAITING) {
          if (i === 0) {
            p.currentPhase = SubQStreamingPhase.SUB_QUERIES;
          } else {
            const prevP = progressRef.current[i - 1];
            if (
              prevP.currentPhase === SubQStreamingPhase.ANSWER ||
              prevP.currentPhase === SubQStreamingPhase.COMPLETE
            ) {
              p.currentPhase = SubQStreamingPhase.SUB_QUERIES;
            }
          }
        }

        switch (p.currentPhase) {
          case SubQStreamingPhase.SUB_QUERIES: {
            const subQueries = sq.sub_queries || [];
            const docs = sq.context_docs?.top_documents || [];
            const hasDocs = docs.length > 0;
            const hasAnswer = !!sq.answer?.length;

            if (p.subQueryIndex < subQueries.length) {
              const currentSubQ = subQueries[p.subQueryIndex];
              // Make sure we have a slot
              while (dynSQ.sub_queries!.length <= p.subQueryIndex) {
                const orig = subQueries[dynSQ.sub_queries!.length];
                dynSQ.sub_queries!.push({
                  query: "",
                  query_id: orig.query_id,
                });
              }

              const dynSubQ = dynSQ.sub_queries![p.subQueryIndex];
              const nextIndex = p.subQueryCharIndex + 1;
              dynSubQ.query = currentSubQ.query.slice(0, nextIndex);
              p.subQueryCharIndex = nextIndex;

              // Move to next subquery if done
              if (nextIndex >= currentSubQ.query.length) {
                p.subQueryIndex++;
                p.subQueryCharIndex = 0;
              }
            } else if (hasDocs || hasAnswer) {
              // Done with subqueries, move to docs
              p.currentPhase = SubQStreamingPhase.CONTEXT_DOCS;
              p.lastDocTimestamp = null; // reset doc timestamp
            }
            break;
          }

          case SubQStreamingPhase.CONTEXT_DOCS: {
            const docs = sq.context_docs?.top_documents || [];
            const hasAnswer = !!sq.answer?.length;
            if (hasAnswer && docs.length === 0) {
              p.currentPhase = SubQStreamingPhase.ANSWER;
              break;
            }

            if (p.docIndex < docs.length) {
              // Check if we have waited long enough since the last doc
              const now = Date.now();
              if (
                p.lastDocTimestamp === null ||
                now - p.lastDocTimestamp >= DOC_DELAY_MS
              ) {
                const docToAdd = docs[p.docIndex];
                const alreadyAdded = dynSQ.context_docs?.top_documents.some(
                  (d) => d.document_id === docToAdd.document_id
                );
                if (!alreadyAdded) {
                  dynSQ.context_docs?.top_documents.push(docToAdd);
                }
                p.docIndex++;
                p.lastDocTimestamp = now; // update the timestamp
              }
            } else if (hasAnswer) {
              // Done with docs, move to answer
              p.currentPhase = SubQStreamingPhase.ANSWER;
            }
            break;
          }

          case SubQStreamingPhase.ANSWER: {
            const answerText = sq.answer || "";

            if (p.answerCharIndex < answerText.length) {
              const nextIndex = p.answerCharIndex + 1;
              dynSQ.answer = answerText.slice(0, nextIndex);
              p.answerCharIndex = nextIndex;
              if (nextIndex >= answerText.length && sq.is_complete) {
                dynSQ.is_complete = true;
                if (
                  dynamicSubQuestionsRef.current.length > 0 &&
                  dynSQ.level_question_nr + 1 ===
                    Math.max(
                      ...dynamicSubQuestionsRef.current.map(
                        (sq) => sq.level_question_nr
                      )
                    )
                ) {
                  console.log("for real finishing", dynSQ.level_question_nr);
                  allowStreaming();
                }
                console.log(
                  "FINISHING",
                  dynSQ.level_question_nr,
                  dynamicSubQuestionsRef.current.length,
                  Math.max(
                    ...dynamicSubQuestionsRef.current.map(
                      (sq) => sq.level_question_nr
                    )
                  )
                );

                p.currentPhase = SubQStreamingPhase.COMPLETE;
              }
            }
            break;
          }

          case SubQStreamingPhase.COMPLETE:
          case SubQStreamingPhase.WAITING:
          default:
            break;
        }
      }

      // Update the UI
      setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);

      // if (
      //   dynamicSubQuestionsRef.current &&
      //   dynamicSubQuestionsRef.current[3] &&
      //   dynamicSubQuestionsRef.current[3].answer &&
      //   dynamicSubQuestionsRef.current[3].answer.length > 0
      // ) {
      //   allowStreaming();
      //   return;
      // }

      setTimeout(loadNextPiece, 5);
    }

    loadNextPiece();

    return () => {
      stop = true;
    };
  }, []);

  return { dynamicSubQuestions };
};
