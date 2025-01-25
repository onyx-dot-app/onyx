"use client";
import React, { useEffect, useRef, useState } from "react";
import {
  Tooltip,
  TooltipTrigger,
  TooltipProvider,
  TooltipContent,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { FiChevronRight, FiChevronDown, FiGlobe } from "react-icons/fi";
import { CheckIcon } from "lucide-react";
import { CirclingArrowIcon } from "@/components/icons/icons";
import { StatusIndicator, ToggleState } from "./message/SubQuestionsDisplay";

// Replace with your actual icons/components
// import { CheckIcon, CirclingArrowIcon } from "@/your-icons-or-components";

/** --------------------------------------------------------------------------------
 * 1. StreamingPhase + Display Text
 *    We add a pseudo "COMPARE" phase before COMPLETE to show "Comparing results"
 *    for at least 0.5 seconds.
 * -------------------------------------------------------------------------------- */
export enum StreamingPhase {
  WAITING = "WAITING",
  SUB_QUERIES = "SUB_QUERIES",
  CONTEXT_DOCS = "CONTEXT_DOCS",
  ANSWER = "ANSWER",
  COMPARE = "COMPARE",
  COMPLETE = "COMPLETE",
  EVALUATE = "EVALUATE",
}

export const StreamingPhaseText: Record<StreamingPhase, string> = {
  [StreamingPhase.WAITING]: "Extracting key concepts",
  [StreamingPhase.SUB_QUERIES]: "Identifying additional questions",
  [StreamingPhase.CONTEXT_DOCS]: "Reading more documents",
  [StreamingPhase.ANSWER]: "Generating refined answer",
  [StreamingPhase.EVALUATE]: "Evaluating new context",
  [StreamingPhase.COMPARE]: "Comparing results",
  [StreamingPhase.COMPLETE]: "Finished",
};

/** --------------------------------------------------------------------------------
 * 2. Ordered Phases: Ensure the COMPARE phase is inserted before COMPLETE
 * -------------------------------------------------------------------------------- */
const PHASES_ORDER: StreamingPhase[] = [
  StreamingPhase.WAITING,
  StreamingPhase.SUB_QUERIES,
  StreamingPhase.CONTEXT_DOCS,
  StreamingPhase.ANSWER,
  StreamingPhase.COMPARE,
  StreamingPhase.COMPLETE,
];

/** --------------------------------------------------------------------------------
 * 3. Hook to queue up phases in order, each with a minimum visible time of 0.5s
 * -------------------------------------------------------------------------------- */
export function useOrderedPhases(externalPhase: StreamingPhase) {
  const [phaseQueue, setPhaseQueue] = useState<StreamingPhase[]>([]);
  const [displayedPhases, setDisplayedPhases] = useState<StreamingPhase[]>([]);
  const lastDisplayTimeRef = useRef<number>(Date.now());
  const MIN_DELAY = 1000; // 0.5 seconds

  const getPhaseIndex = (phase: StreamingPhase) => PHASES_ORDER.indexOf(phase);

  // Whenever externalPhase changes, add any missing steps into the queue
  useEffect(() => {
    setPhaseQueue((prevQueue) => {
      const lastDisplayed = displayedPhases[displayedPhases.length - 1];
      const lastIndex = lastDisplayed
        ? getPhaseIndex(lastDisplayed)
        : getPhaseIndex(StreamingPhase.WAITING);

      let targetPhase = externalPhase;
      let targetIndex = getPhaseIndex(targetPhase);

      // If externalPhase is COMPLETE, show "COMPARE" first (unless we've shown it already)
      if (externalPhase === StreamingPhase.COMPLETE) {
        if (!displayedPhases.includes(StreamingPhase.COMPARE)) {
          targetPhase = StreamingPhase.COMPARE;
          targetIndex = getPhaseIndex(targetPhase);
        }
      }

      // If the new target is before or at the last displayed, do nothing
      if (targetIndex <= lastIndex) {
        return prevQueue;
      }

      // Otherwise, collect all missing phases from lastDisplayed+1 up to targetIndex
      const missingPhases: StreamingPhase[] = [];
      for (let i = lastIndex + 1; i <= targetIndex; i++) {
        missingPhases.push(PHASES_ORDER[i]);
      }
      return [...prevQueue, ...missingPhases];
    });
  }, [externalPhase, displayedPhases]);

  // Process the queue, displaying each queued phase for at least MIN_DELAY (0.5s)
  useEffect(() => {
    if (phaseQueue.length === 0) return;

    let rafId: number;
    const processQueue = () => {
      const now = Date.now();

      if (now - lastDisplayTimeRef.current >= MIN_DELAY) {
        setPhaseQueue((prevQueue) => {
          if (prevQueue.length > 0) {
            const [nextPhase, ...rest] = prevQueue;
            setDisplayedPhases((prev) => [...prev, nextPhase]);
            lastDisplayTimeRef.current = Date.now();
            return rest;
          }
          return prevQueue;
        });
      }
      rafId = requestAnimationFrame(processQueue);
    };

    rafId = requestAnimationFrame(processQueue);
    return () => cancelAnimationFrame(rafId);
  }, [phaseQueue]);

  // displayedPhases are the ones currently shown, in the order they appeared
  return displayedPhases;
}

/** --------------------------------------------------------------------------------
 * 4. StatusIndicator: shows "running" (spinner) or "finished" (check)
 * -------------------------------------------------------------------------------- */

/** --------------------------------------------------------------------------------
 * 5. Example SubQuestionDetail interface (from your snippet)
 * -------------------------------------------------------------------------------- */
export interface SubQuestionDetail {
  question: string;
  answer: string;
  sub_queries?: { query: string }[] | null;
  context_docs?: { top_documents: any[] } | null;
  is_complete?: boolean;
}

/** --------------------------------------------------------------------------------
 * 6. Final "RefinemenetBadge" component
 *    - Renders a "Refining" box with phases shown in order
 *    - Disappears once COMPLETE is reached, unless hovered
 *    - Preserves any states already shown
 * -------------------------------------------------------------------------------- */
export default function RefinemenetBadge({
  overallAnswer,
  secondLevelSubquestions,
  toggleInitialAnswerVieinwg,
  isViewingInitialAnswer,
  finished,
}: {
  finished: boolean;
  overallAnswer: string;
  secondLevelSubquestions?: SubQuestionDetail[] | null;
  toggleInitialAnswerVieinwg: () => void;
  isViewingInitialAnswer: boolean;
}) {
  // Derive the 'externalPhase' from your existing logic:
  const currentState =
    overallAnswer.length > 0
      ? finished
        ? StreamingPhase.COMPLETE
        : StreamingPhase.ANSWER
      : secondLevelSubquestions?.[0]
        ? secondLevelSubquestions.every((q) => q.answer && q.answer.length > 0)
          ? StreamingPhase.EVALUATE
          : secondLevelSubquestions?.[0].context_docs
            ? StreamingPhase.CONTEXT_DOCS
            : secondLevelSubquestions?.[0].sub_queries
              ? StreamingPhase.SUB_QUERIES
              : StreamingPhase.WAITING
        : StreamingPhase.WAITING;

  //     secondLevelSubquestions?.[0]
  //     : secondLevelSubquestions[0].context_docs
  //     ? StreamingPhase.CONTEXT_DOCS
  //     : secondLevelSubquestions[0].sub_queries
  //     ? StreamingPhase.SUB_QUERIES
  //     : secondLevelSubquestions[0].question
  //     ? StreamingPhase.WAITING
  //     : StreamingPhase.WAITING
  //   : StreamingPhase.WAITING;

  // Once the first query token comes through, it should be in the sub queries
  // Once the first set of documents come through it should be in context docs
  // Once all of the analysis have started generating, it should say evaluate
  // Once the refined answer starts generating, it should say Answer
  // Once the refined answer finishes generating, show COMPARE (we don't have this yet)

  // export const StreamingPhaseText: Record<StreamingPhase, string> = {
  //     [StreamingPhase.WAITING]: "Extracting key concepts",
  //     [StreamingPhase.SUB_QUERIES]: "Identifying additional questions",
  //     [StreamingPhase.CONTEXT_DOCS]: "Reading more documents",
  //     [StreamingPhase.ANSWER]: "Generating refined answer",
  //     [StreamingPhase.EVALUATE]: "Evaluating new context",
  //     [StreamingPhase.COMPARE]: "Comparing results",
  //     [StreamingPhase.COMPLETE]: "Finished",
  //   };

  // Get the array of displayed phases
  const displayedPhases = useOrderedPhases(currentState);
  const isDone = displayedPhases.includes(StreamingPhase.COMPLETE);

  // Expand/collapse, hover states
  const [expanded, setExpanded] = useState(true);
  const [isHovered, setIsHovered] = useState(false);
  const [shouldShow, setShouldShow] = useState(true);

  // Once "done", hide after a short delay if not hovered
  useEffect(() => {
    if (isDone) {
      const timer = setTimeout(() => {
        if (!isHovered) {
          setShouldShow(false);
        }
      }, 800); // e.g. 0.8s
      return () => clearTimeout(timer);
    }
  }, [isDone, isHovered]);

  if (!shouldShow) {
    return null; // entire box disappears
  }

  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <div
          className="relative w-fit max-w-sm"
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => setIsHovered(false)}
        >
          {/* Original snippet's tooltip usage */}
          <TooltipTrigger asChild>
            <div
              className="flex loading-text items-center gap-x-2 text-black text-sm 
                         font-medium cursor-pointer hover:text-blue-600 
                         transition-colors duration-200"
            >
              <p className="text-sm font-medium">Refining Answer</p>
              <FiChevronRight
                className={`inline-block my-auto transition-transform duration-200 text-text-darker ${
                  isHovered ? "rotate-90" : ""
                }`}
                size={16}
              />
            </div>
          </TooltipTrigger>
          <TooltipContent
            side="bottom"
            align="start"
            className="w-fit p-4 bg-white border-2 border-border shadow-lg rounded-md"
          >
            {/* If not done, show the "Refining" box + a chevron */}

            {/* Expanded area: each displayed phase in order */}
            {expanded && (
              <div className="items-start flex flex-col gap-y-2">
                {currentState !== StreamingPhase.WAITING ? (
                  Array.from(new Set(displayedPhases)).map((phase, index) => {
                    const phaseIndex = displayedPhases.indexOf(phase);
                    // The last displayed item is "running" if not COMPLETE
                    let status = ToggleState.Done;
                    if (
                      index ===
                      Array.from(new Set(displayedPhases)).length - 1
                    ) {
                      status = ToggleState.InProgress;
                    }
                    if (phase === StreamingPhase.COMPLETE) {
                      status = ToggleState.Done;
                    }

                    return (
                      <div
                        key={phase}
                        className="text-text flex items-center justify-start gap-x-2"
                      >
                        <div className="w-3 h-3">
                          <StatusIndicator status={status} />
                        </div>
                        <span className="text-sm font-medium">
                          {StreamingPhaseText[phase]}
                        </span>
                      </div>
                    );
                  })
                ) : (
                  <div
                    key={currentState}
                    className="text-text flex items-center justify-start gap-x-2"
                  >
                    <div className="w-3 h-3">
                      <StatusIndicator status={ToggleState.InProgress} />
                    </div>
                    <span className="text-sm font-medium">
                      {StreamingPhaseText[StreamingPhase.SUB_QUERIES]}
                    </span>
                  </div>
                )}
              </div>
            )}
          </TooltipContent>
        </div>
      </Tooltip>
    </TooltipProvider>
  );
}

// "use client";
// import {
//   Tooltip,
//   TooltipTrigger,
//   TooltipProvider,
//   TooltipContent,
// } from "@/components/ui/tooltip";
// import { Button } from "@/components/ui/button";
// import { FiChevronRight, FiGlobe } from "react-icons/fi";
// import {
//   StreamingPhase,
//   StreamingPhaseText,
// } from "./message/StreamingMessages";
// import { SubQuestionDetail } from "./interfaces";
// import { useEffect, useRef, useState } from "react";

// const PHASES_ORDER: StreamingPhase[] = [
//   StreamingPhase.WAITING,
//   StreamingPhase.SUB_QUERIES,
//   StreamingPhase.CONTEXT_DOCS,
//   StreamingPhase.ANSWER,
//   StreamingPhase.COMPLETE,
// ];

// export function useOrderedPhases(externalPhase: StreamingPhase) {
//   const [phaseQueue, setPhaseQueue] = useState<StreamingPhase[]>([]);
//   const [displayedPhase, setDisplayedPhase] = useState<StreamingPhase>(
//     StreamingPhase.WAITING
//   );
//   const lastDisplayTimestampRef = useRef<number>(Date.now());

//   const getPhaseIndex = (phase: StreamingPhase) => {
//     return PHASES_ORDER.indexOf(phase);
//   };

//   useEffect(() => {
//     setPhaseQueue((prevQueue) => {
//       const lastQueuedPhase =
//         prevQueue.length > 0 ? prevQueue[prevQueue.length - 1] : displayedPhase;

//       const lastQueuedIndex = getPhaseIndex(lastQueuedPhase);
//       const externalIndex = getPhaseIndex(externalPhase);

//       if (externalIndex <= lastQueuedIndex) {
//         return prevQueue;
//       }

//       const missingPhases: StreamingPhase[] = [];
//       for (let i = lastQueuedIndex + 1; i <= externalIndex; i++) {
//         missingPhases.push(PHASES_ORDER[i]);
//       }
//       return [...prevQueue, ...missingPhases];
//     });
//   }, [externalPhase, displayedPhase]);

//   useEffect(() => {
//     if (phaseQueue.length === 0) return;
//     let rafId: number;

//     const processQueue = () => {
//       const now = Date.now();
//       const elapsed = now - lastDisplayTimestampRef.current;

//       // Keep this at 1000ms from the original example (unchanged),
//       // but you can adjust if you want a different visible time in *this* component.
//       if (elapsed >= 1000) {
//         setPhaseQueue((prevQueue) => {
//           if (prevQueue.length > 0) {
//             const [next, ...rest] = prevQueue;
//             setDisplayedPhase(next);
//             lastDisplayTimestampRef.current = Date.now();
//             return rest;
//           }
//           return prevQueue;
//         });
//       }
//       rafId = requestAnimationFrame(processQueue);
//     };

//     rafId = requestAnimationFrame(processQueue);
//     return () => {
//       if (rafId) {
//         cancelAnimationFrame(rafId);
//       }
//     };
//   }, [phaseQueue]);

//   return StreamingPhaseText[displayedPhase];
// }

// export default function RefinemenetBadge({
//   secondLevelSubquestions,
//   toggleInitialAnswerVieinwg,
//   isViewingInitialAnswer,
// }: {
//   secondLevelSubquestions?: SubQuestionDetail[] | null;
//   toggleInitialAnswerVieinwg: () => void;
//   isViewingInitialAnswer: boolean;
// }) {
//   const currentState = secondLevelSubquestions?.[0]
//     ? secondLevelSubquestions[0].answer
//       ? secondLevelSubquestions[0].is_complete
//         ? StreamingPhase.COMPLETE
//         : StreamingPhase.ANSWER
//       : secondLevelSubquestions[0].context_docs
//       ? StreamingPhase.CONTEXT_DOCS
//       : secondLevelSubquestions[0].sub_queries
//       ? StreamingPhase.SUB_QUERIES
//       : secondLevelSubquestions[0].question
//       ? StreamingPhase.WAITING
//       : StreamingPhase.WAITING
//     : StreamingPhase.WAITING;

//   const message = useOrderedPhases(currentState);

//   return (
//     <TooltipProvider delayDuration={0}>
//       <Tooltip>
//         <TooltipTrigger asChild>
//           <div className="flex loading-text items-center gap-x-2 text-black text-sm font-medium cursor-pointer hover:text-blue-600 transition-colors duration-200">
//             Refining answer...
//             <FiChevronRight
//               className="inline-block text-text-darker"
//               size={16}
//             />
//           </div>
//         </TooltipTrigger>
//         <TooltipContent className="w-80 p-4 bg-white shadow-lg rounded-md">
//           <div className="space-y-4">
//             <p className="text-lg leading-none font-semibold text-gray-800">
//               {message}
//             </p>
//             <p className="text-sm text-gray-600">
//               The answer is being refined based on additional context and
//               analysis.
//             </p>
//             <Button
//               onClick={() => toggleInitialAnswerVieinwg()}
//               size="sm"
//               className="w-full"
//             >
//               {isViewingInitialAnswer
//                 ? "See Live Updates"
//                 : "Hide Live Updates"}
//               <FiGlobe className="inline-block mr-2" />
//             </Button>
//           </div>
//         </TooltipContent>
//       </Tooltip>
//     </TooltipProvider>
//   );
// }

// import React, { useState, useEffect } from "react";

export const NoNewAnswerMessage = () => {
  const [opacity, setOpacity] = useState(1);

  useEffect(() => {
    const fadeOutDuration = 2000; // 2 seconds
    const intervalDuration = 50; // Update every 50ms for smooth fade
    const opacityStep = intervalDuration / fadeOutDuration;

    const fadeOutInterval = setInterval(() => {
      setOpacity((prevOpacity) => {
        const newOpacity = prevOpacity - opacityStep;
        return newOpacity > 0 ? newOpacity : 0;
      });
    }, intervalDuration);

    const timer = setTimeout(() => {
      clearInterval(fadeOutInterval);
    }, fadeOutDuration);

    return () => {
      clearInterval(fadeOutInterval);
      clearTimeout(timer);
    };
  }, []);

  if (opacity === 0) return null;

  return (
    <div className="text-gray-600 text-sm" style={{ opacity: opacity }}>
      {/* No new answer found... */}
    </div>
  );
};
