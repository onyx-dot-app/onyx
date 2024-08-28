"use client";

import {
  Dispatch,
  SetStateAction,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { HoverableIcon } from "../Hoverable";
import {
  DislikeFeedbackIcon,
  LikeFeedbackIcon,
  ToggleDown,
} from "../icons/icons";
import { FeedbackType } from "@/app/chat/types";
import { searchState } from "./SearchSection";
import { SettingsContext } from "../settings/SettingsProvider";
import { AnswerSection } from "./results/AnswerSection";
import { Quote, SearchResponse } from "@/lib/search/interfaces";
import { QuotesSection } from "./results/QuotesSection";

export default function SearchAnswer({
  searchAnswerExpanded,
  setSearchAnswerExpanded,
  isFetching,
  dedupedQuotes,
  searchResponse,
  setCurrentFeedback,
  searchState,
}: {
  searchAnswerExpanded: boolean;
  setSearchAnswerExpanded: Dispatch<SetStateAction<boolean>>;
  isFetching: boolean;
  dedupedQuotes: Quote[];
  searchResponse: SearchResponse;
  searchState: searchState;
  setCurrentFeedback: Dispatch<SetStateAction<[FeedbackType, number] | null>>;
}) {
  const [searchAnswerOverflowing, setSearchAnswerOverflowing] = useState(false);

  const { quotes, answer, error } = searchResponse;
  const answerContainerRef = useRef<HTMLDivElement>(null);

  const handleFeedback = (feedbackType: FeedbackType, messageId: number) => {
    setCurrentFeedback([feedbackType, messageId]);
  };

  const settings = useContext(SettingsContext);

  useEffect(() => {
    const checkOverflow = () => {
      if (answerContainerRef.current) {
        const isOverflowing =
          answerContainerRef.current.scrollHeight >
          answerContainerRef.current.clientHeight;
        setSearchAnswerOverflowing(isOverflowing);
      }
    };

    checkOverflow();
    window.addEventListener("resize", checkOverflow);

    return () => {
      window.removeEventListener("resize", checkOverflow);
    };
  }, [answer, quotes]);

  return (
    <div
      ref={answerContainerRef}
      className={`my-4 ${searchAnswerExpanded ? "min-h-[16rem]" : "h-[16rem]"} ${!searchAnswerExpanded && searchAnswerOverflowing && "overflow-y-hidden"} p-4 border-2 border-border rounded-lg relative`}
    >
      <div>
        <div className="flex gap-x-2">
          <h2 className="text-emphasis font-bold my-auto mb-1 ">AI Answer</h2>

          {searchState == "generating" && (
            <div key={"generating"} className="relative inline-block">
              <span className="loading-text">Generating response...</span>
            </div>
          )}

          {searchState == "citing" && (
            <div key={"citing"} className="relative inline-block">
              <span className="loading-text">Creating citations...</span>
            </div>
          )}

          {searchState == "searching" && (
            <div key={"Reading"} className="relative inline-block">
              <span className="loading-text">Searching...</span>
            </div>
          )}

          {searchState == "reading" && (
            <div key={"Reading"} className="relative inline-block">
              <span className="loading-text">
                Reading{settings?.isMobile ? "" : " Documents"}
                ...
              </span>
            </div>
          )}

          {searchState == "analyzing" && (
            <div key={"Generating"} className="relative inline-block">
              <span className="loading-text">
                Running
                {settings?.isMobile ? "" : " Analysis"}...
              </span>
            </div>
          )}
        </div>

        <div className={`pt-1 h-auto border-t border-border w-full`}>
          <AnswerSection
            answer={answer}
            quotes={quotes}
            error={error}
            isFetching={isFetching}
          />
        </div>

        <div className="w-full">
          {quotes !== null && quotes.length > 0 && answer && (
            <QuotesSection quotes={dedupedQuotes} isFetching={isFetching} />
          )}

          {searchResponse.messageId !== null && (
            <div className="absolute right-3 flex bottom-3">
              <HoverableIcon
                icon={<LikeFeedbackIcon />}
                onClick={() =>
                  handleFeedback("like", searchResponse?.messageId as number)
                }
              />
              <HoverableIcon
                icon={<DislikeFeedbackIcon />}
                onClick={() =>
                  handleFeedback("dislike", searchResponse?.messageId as number)
                }
              />
            </div>
          )}
        </div>
      </div>
      {!searchAnswerExpanded && searchAnswerOverflowing && (
        <div className="absolute bottom-0 left-0 w-full h-[100px] bg-gradient-to-b from-background/5 via-background/60 to-background/90"></div>
      )}

      {!searchAnswerExpanded && searchAnswerOverflowing && (
        <div className="w-full h-12 absolute items-center content-center flex left-0 px-4 bottom-0">
          <button
            onClick={() => setSearchAnswerExpanded(true)}
            className="flex gap-x-1 items-center justify-center hover:bg-background-100 cursor-pointer max-w-sm text-sm mx-auto w-full bg-background border py-2 rounded-full"
          >
            Show more
            <ToggleDown />
          </button>
        </div>
      )}
    </div>
  );
}
