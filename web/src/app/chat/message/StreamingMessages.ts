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
  // Tracks if we're done with the high-level question
  questionDone: boolean;
  // How far we've typed in the question so far
  questionCharIndex: number;
  // Current streaming phase (subQueries → contextDocs → answer)
  currentPhase: SubQStreamingPhase;
  // Sub-query streaming progress
  subQueryIndex: number;
  subQueryCharIndex: number;
  // Context docs streaming progress
  docIndex: number;
  lastDocTimestamp: number | null;
  // Answer streaming progress
  answerCharIndex: number;
}

const DOC_DELAY_MS = 100;

export const useStreamingMessages = (
  subQuestions: SubQuestionDetail[],
  allowStreaming: () => void
) => {
  // The array we show the user, progressively revealed
  const [dynamicSubQuestions, setDynamicSubQuestions] = useState<
    SubQuestionDetail[]
  >([]);

  // Keep the latest subQuestions in a ref for streaming logic
  const subQuestionsRef = useRef<SubQuestionDetail[]>(subQuestions);
  useEffect(() => {
    subQuestionsRef.current = subQuestions;
  }, [subQuestions]);

  // Our in-progress "dynamic" array
  const dynamicSubQuestionsRef = useRef<SubQuestionDetail[]>([]);

  // Per-subquestion streaming progress
  const progressRef = useRef<SubQuestionProgress[]>([]);

  /**
   * This effect ensures that if subQuestions is updated with
   * new items at the end, we create progress entries for them.
   * We do NOT reset progress for older items (so they keep streaming).
   */
  useEffect(() => {
    subQuestions.forEach((sq, i) => {
      // If we *already* have a progress object for subquestion i,
      // do nothing—let it continue wherever it was.
      if (!progressRef.current[i]) {
        // This is a *new* subquestion we haven't seen before, so create a fresh object:
        progressRef.current[i] = {
          questionDone: false,
          questionCharIndex: 0,
          // For subquestion #0, start in SUB_QUERIES;
          // for others, start in WAITING until the previous subQ hits ANSWER/COMPLETE.
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

      // Also ensure our dynamic array has a slot for index i
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

    // Force update so the UI can show placeholders for new subquestions
    setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);
  }, [subQuestions]);

  /**
   * Main streaming loop:
   *  - Streams each subquestion's `question` in parallel.
   *  - Once all question text is done (for each subquestion),
   *    it processes phases SUB_QUERIES → CONTEXT_DOCS → ANSWER → COMPLETE,
   *    though subquestion #i waits for subquestion #(i-1) to at least
   *    start ANSWER before moving beyond WAITING.
   */
  useEffect(() => {
    let stop = false; // set to true if unmounting

    function loadNextPiece() {
      if (stop) return;

      const actualSubQs = subQuestionsRef.current;
      if (!actualSubQs || actualSubQs.length === 0) {
        // No subquestions at all, check again soon
        setTimeout(loadNextPiece, 100);
        return;
      }

      // 1) Stream high-level questions in parallel
      let didStreamQuestion = false;
      for (let i = 0; i < actualSubQs.length; i++) {
        const sq = actualSubQs[i];
        const p = progressRef.current[i];
        const dynSQ = dynamicSubQuestionsRef.current[i];

        // If we haven't typed the entire question yet, or even if we have, try to type one more char
        if (sq.question) {
          const nextIndex = p.questionCharIndex + 1;
          if (nextIndex <= sq.question.length) {
            dynSQ.question = sq.question.slice(0, nextIndex);
            p.questionCharIndex = nextIndex;
            if (nextIndex >= sq.question.length) {
              p.questionDone = true;
            }
            didStreamQuestion = true;
          }
        }
      }

      // If we typed any question chars, let's pause briefly and come back
      // so subqueries/docs/answers don't block question streaming
      if (didStreamQuestion) {
        setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);
        setTimeout(loadNextPiece, 15);
        return;
      }

      // 2) If no question chars were typed, proceed with SUB_QUERIES → CONTEXT_DOCS → ANSWER
      for (let i = 0; i < actualSubQs.length; i++) {
        const sq = actualSubQs[i];
        const dynSQ = dynamicSubQuestionsRef.current[i];
        const p = progressRef.current[i];

        // If this subquestion is WAITING, see if we can transition
        if (p.currentPhase === SubQStreamingPhase.WAITING) {
          if (i === 0) {
            // subquestion #0 can start immediately
            p.currentPhase = SubQStreamingPhase.SUB_QUERIES;
          } else {
            // Others wait until subquestion #(i-1) is in ANSWER or COMPLETE
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

            // Type subqueries in order, one char at a time
            if (p.subQueryIndex < subQueries.length) {
              const currentSubQ = subQueries[p.subQueryIndex];
              while (dynSQ.sub_queries!.length <= p.subQueryIndex) {
                // Create an empty subquery in dynamic
                dynSQ.sub_queries!.push({
                  query: "",
                  query_id: subQueries[dynSQ.sub_queries!.length].query_id,
                });
              }

              // Update previous dynamic subqueries if they're shorter than current subqueries
              for (let j = 0; j < p.subQueryIndex; j++) {
                if (
                  dynSQ.sub_queries![j].query.length <
                  subQueries[j].query.length
                ) {
                  dynSQ.sub_queries![j].query = subQueries[j].query;
                }
              }

              const dynSubQ = dynSQ.sub_queries![p.subQueryIndex];
              const nextIndex = p.subQueryCharIndex + 1;

              dynSubQ.query = currentSubQ.query.slice(0, nextIndex);
              p.subQueryCharIndex = nextIndex;

              if (nextIndex >= currentSubQ.query.length) {
                p.subQueryIndex++;
                p.subQueryCharIndex = 0;
              }
            } else if (hasDocs || hasAnswer) {
              // If we've typed all known subqueries, and we see docs or answer,
              // we move on to CONTEXT_DOCS
              p.currentPhase = SubQStreamingPhase.CONTEXT_DOCS;
              p.lastDocTimestamp = null; // reset doc timestamp
            }
            break;
          }

          case SubQStreamingPhase.CONTEXT_DOCS: {
            const docs = sq.context_docs?.top_documents || [];
            const hasAnswer = !!sq.answer?.length;

            // If we see an answer but no docs, jump to ANSWER
            if (hasAnswer && docs.length === 0) {
              p.currentPhase = SubQStreamingPhase.ANSWER;
              break;
            }

            // Otherwise, add docs one at a time
            if (p.docIndex < docs.length) {
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
                p.lastDocTimestamp = now;
              }
            } else if (hasAnswer) {
              // Once we've added all known docs and see an answer, move on
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

              // If we typed the entire answer and we consider it "complete"
              if (nextIndex >= answerText.length && sq.is_complete) {
                dynSQ.is_complete = true;
                p.currentPhase = SubQStreamingPhase.COMPLETE;

                // If you want, you can check if this is the last subquestion
                // and call allowStreaming() or do some final logic.

                if (
                  sq.level_question_nr ===
                  Math.max(
                    ...subQuestions
                      .filter((q) => q.level === 0)
                      .map((q) => q.level_question_nr)
                  )
                ) {
                  allowStreaming();
                }
              }
            }
            break;
          }

          case SubQStreamingPhase.COMPLETE:
          case SubQStreamingPhase.WAITING:
          default:
            // No streaming needed in these phases
            break;
        }
      }

      // Update UI
      setDynamicSubQuestions([...dynamicSubQuestionsRef.current]);

      setTimeout(loadNextPiece, 5);
    }

    loadNextPiece();

    return () => {
      stop = true;
    };
  }, []);

  return { dynamicSubQuestions };
};
