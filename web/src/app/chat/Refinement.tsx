"use client";
import React, { useEffect, useRef, useState } from "react";
import {
  Tooltip,
  TooltipTrigger,
  TooltipProvider,
  TooltipContent,
} from "@/components/ui/tooltip";
import { FiChevronRight } from "react-icons/fi";
import { StatusIndicator, ToggleState } from "./message/SubQuestionsDisplay";
import { SubQuestionDetail } from "./interfaces";
import {
  PHASES_ORDER,
  StreamingPhase,
  StreamingPhaseText,
} from "./message/StreamingMessages";
import { Badge } from "@/components/ui/badge";

export function useOrderedPhases(externalPhase: StreamingPhase) {
  const [phaseQueue, setPhaseQueue] = useState<StreamingPhase[]>([]);
  const [displayedPhases, setDisplayedPhases] = useState<StreamingPhase[]>([]);
  const lastDisplayTimeRef = useRef<number>(Date.now());
  const MIN_DELAY = 300; // 0.5 seconds

  const getPhaseIndex = (phase: StreamingPhase) => PHASES_ORDER.indexOf(phase);
  const finalPhaseIndex = useRef<number | null>(null);

  // Whenever externalPhase changes, add any missing steps into the queue
  useEffect(() => {
    setPhaseQueue((prevQueue) => {
      const lastIndex = finalPhaseIndex.current || 0;

      let targetPhase = externalPhase;
      let targetIndex = getPhaseIndex(targetPhase);

      // If the new target is before or at the last displayed, do nothing
      if (targetIndex <= lastIndex) {
        return prevQueue;
      }

      finalPhaseIndex.current = targetIndex;

      // Otherwise, collect all missing phases from lastDisplayed+1 up to targetIndex
      const missingPhases: StreamingPhase[] = PHASES_ORDER.slice(
        0,
        targetIndex + 1
      );

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

  return displayedPhases;
}

export function RefinemenetBadge({
  setToolTipHovered,
  overallAnswer,
  secondLevelSubquestions,
  finished,
  setCanShowResponse,
  canShowResponse,
}: {
  setToolTipHovered: (hovered: boolean) => void;
  finished: boolean;
  overallAnswer: string;
  secondLevelSubquestions?: SubQuestionDetail[] | null;
  setCanShowResponse: (canShowResponse: boolean) => void;
  canShowResponse: boolean;
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

  // Get the array of displayed phases
  const displayedPhases = useOrderedPhases(currentState);
  const isDone = displayedPhases.includes(StreamingPhase.COMPLETE);

  // Expand/collapse, hover states
  const [expanded] = useState(true);
  const [toolTipHoveredInternal, setToolTipHoveredInternal] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [shouldShow, setShouldShow] = useState(true);

  // Refs for bounding area checks
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  // Keep the tooltip open if hovered on container or tooltip
  // Remove the old onMouseLeave calls and rely on bounding area checks
  useEffect(() => {
    function handleMouseMove(e: MouseEvent) {
      if (!containerRef.current || !tooltipRef.current) return;

      const containerRect = containerRef.current.getBoundingClientRect();
      const tooltipRect = tooltipRef.current.getBoundingClientRect();
      const [x, y] = [e.clientX, e.clientY];

      const inContainer =
        x >= containerRect.left &&
        x <= containerRect.right &&
        y >= containerRect.top &&
        y <= containerRect.bottom;

      const inTooltip =
        x >= tooltipRect.left &&
        x <= tooltipRect.right &&
        y >= tooltipRect.top &&
        y <= tooltipRect.bottom;

      // If not hovering in either region, close tooltip
      if (!inContainer && !inTooltip) {
        setToolTipHoveredInternal(false);
        setToolTipHovered(false);
        setIsHovered(false);
      }
    }

    window.addEventListener("mousemove", handleMouseMove);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
    };
  }, [setToolTipHovered]);

  // Once "done", hide after a short delay if not hovered
  useEffect(() => {
    if (isDone) {
      const timer = setTimeout(() => {
        setShouldShow(false);
        setCanShowResponse(true);
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [isDone, isHovered, setCanShowResponse]);

  if (!shouldShow) {
    return null; // entire box disappears
  }

  return (
    <TooltipProvider delayDuration={0}>
      {/*
        IMPORTANT: We rely on open={ isHovered || toolTipHoveredInternal }
        to keep the tooltip visible if either the badge or tooltip is hovered.
      */}
      <Tooltip open={isHovered || toolTipHoveredInternal}>
        <div
          className="relative w-fit max-w-sm"
          ref={containerRef}
          // onMouseEnter keeps the tooltip open
          onMouseEnter={() => {
            setIsHovered(true);
            setToolTipHoveredInternal(true);
            setToolTipHovered(true);
          }}
          // Remove the explicit onMouseLeave – the global bounding check will close it
        >
          <TooltipTrigger asChild>
            <div className="flex items-center gap-x-1 text-black text-sm font-medium cursor-pointer hover:text-blue-600 transition-colors duration-200">
              <p className="text-sm loading-text font-medium">
                Refining Answer
              </p>
              <FiChevronRight
                className={`inline-block my-auto transition-transform duration-200 text-text-darker ${
                  isHovered ? "rotate-90" : ""
                }`}
                size={16}
              />
            </div>
          </TooltipTrigger>
          {expanded && (
            <TooltipContent
              ref={tooltipRef}
              // onMouseEnter keeps the tooltip open when cursor enters tooltip
              onMouseEnter={() => {
                setToolTipHoveredInternal(true);
                setToolTipHovered(true);
              }}
              // Remove onMouseLeave and rely on bounding box logic to close
              side="bottom"
              align="start"
              width="w-fit"
              className=" -mt-1 p-4 bg-[#fff] dark:bg-[#000] border-2 border-border dark:border-neutral-800 shadow-lg rounded-md"
            >
              {/* If not done, show the "Refining" box + a chevron */}
              {/* Expanded area: each displayed phase in order */}

              <div className="items-start flex flex-col gap-y-2">
                {currentState !== StreamingPhase.WAITING ? (
                  Array.from(new Set(displayedPhases)).map((phase, index) => {
                    let status = ToggleState.Done;
                    if (
                      index ===
                        Array.from(new Set(displayedPhases)).length - 1 &&
                      phase !== StreamingPhase.COMPLETE
                    ) {
                      status = ToggleState.InProgress;
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
            </TooltipContent>
          )}
        </div>
      </Tooltip>
    </TooltipProvider>
  );
}
export const NoNewAnswerMessage = () => {
  const [opacity, setOpacity] = useState(1);
  const [isVisible, setIsVisible] = useState(true);

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
      setIsVisible(false);
    }, fadeOutDuration);

    return () => {
      clearInterval(fadeOutInterval);
      clearTimeout(timer);
    };
  }, []);

  if (!isVisible) return null;

  return (
    <div
      className="text-text-600 text-sm transition-opacity duration-2000 ease-out"
      style={{ opacity: opacity }}
    >
      No new answer found...
    </div>
  );
};

export function StatusRefinement({
  canShowResponse,
  setCanShowResponse,
  isImprovement,
  isViewingInitialAnswer,
  toggleDocDisplay,
  secondLevelSubquestions,
  secondLevelAssistantMessage,
  secondLevelGenerating,
  subQuestions,
  setIsViewingInitialAnswer,
  noShowingMessage,
}: {
  canShowResponse: boolean;
  setCanShowResponse: (canShowResponse: boolean) => void;
  isImprovement?: boolean | null;
  isViewingInitialAnswer: boolean;
  toggleDocDisplay: (isViewingInitialAnswer: boolean) => void;
  secondLevelSubquestions: SubQuestionDetail[] | null;
  secondLevelAssistantMessage: string;
  secondLevelGenerating: boolean;
  subQuestions: SubQuestionDetail[] | null;
  setIsViewingInitialAnswer: (isViewingInitialAnswer: boolean) => void;
  noShowingMessage?: boolean;
}) {
  const [toolTipHovered, setToolTipHovered] = useState(false);
  if (!secondLevelGenerating && isImprovement == undefined) {
    return null;
  }
  if (noShowingMessage && !isImprovement) {
    return <></>;
  }
  return (
    <>
      {(!canShowResponse || isImprovement == null) &&
      subQuestions &&
      subQuestions.length > 0 ? (
        <RefinemenetBadge
          setToolTipHovered={setToolTipHovered}
          setCanShowResponse={setCanShowResponse}
          canShowResponse={canShowResponse || false}
          finished={!secondLevelGenerating}
          overallAnswer={secondLevelAssistantMessage || ""}
          secondLevelSubquestions={secondLevelSubquestions}
        />
      ) : secondLevelAssistantMessage ? (
        isImprovement ? (
          <TooltipProvider delayDuration={0}>
            <Tooltip open={toolTipHovered}>
              <TooltipTrigger
                onMouseLeave={() => setToolTipHovered(false)}
                asChild
              >
                <Badge
                  // NOTE: This is a hack to make the badge slightly higher
                  className="cursor-pointer mt-[1px]"
                  variant={`${
                    isViewingInitialAnswer ? "agent" : "agent-faded"
                  }`}
                  onClick={() => {
                    const viewInitialAnswer = !isViewingInitialAnswer;
                    setIsViewingInitialAnswer(viewInitialAnswer);
                    toggleDocDisplay && toggleDocDisplay(viewInitialAnswer);
                  }}
                >
                  {isViewingInitialAnswer
                    ? "See Refined Answer"
                    : "See Original Answer"}
                </Badge>
              </TooltipTrigger>
              <TooltipContent
                onMouseLeave={() => setToolTipHovered(false)}
                side="bottom"
                align="start"
                width="w-fit"
                className="w-fit p-4 bg-[#fff] border-2 border-border dark:border-neutral-800 shadow-lg rounded-md"
              >
                {/* If not done, show the "Refining" box + a chevron */}

                {/* Expanded area: each displayed phase in order */}

                <div className="items-start flex flex-col gap-y-2">
                  {PHASES_ORDER.map((phase) => (
                    <div
                      key={phase}
                      className="text-text flex items-center justify-start gap-x-2"
                    >
                      <div className="w-3 h-3">
                        <StatusIndicator status={ToggleState.Done} />
                      </div>
                      <span className="text-neutral-800 text-sm font-medium">
                        {StreamingPhaseText[phase]}
                      </span>
                    </div>
                  ))}
                </div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <NoNewAnswerMessage />
        )
      ) : (
        <></>
      )}
    </>
  );
}
