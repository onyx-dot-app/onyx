import React, { useEffect, useState, useRef, useMemo } from "react";
import { FiGlobe } from "react-icons/fi";
import {
  PacketType,
  FetchToolPacket,
  FetchToolStart,
  SectionEnd,
} from "../../../services/streamingModels";
import { MessageRenderer } from "../interfaces";
import { truncateString } from "@/lib/utils";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SourceChip2 } from "@/app/chat/components/SourceChip2";
import { BlinkingDot } from "../../BlinkingDot";

const INITIAL_URLS_TO_SHOW = 3;
const URLS_PER_EXPANSION = 5;
const MAX_TITLE_LENGTH = 25;

const READING_MIN_DURATION_MS = 1000; // 1 second minimum for "Reading" state
const READ_MIN_DURATION_MS = 1000; // 1 second minimum for "Read" state

const constructCurrentFetchState = (
  packets: FetchToolPacket[]
): {
  documents: OnyxDocument[];
  isReading: boolean;
  isComplete: boolean;
} => {
  // Check for fetch tool start packet
  const fetchStart = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_START
  )?.obj as FetchToolStart | null;
  const fetchEnd = packets.find(
    (packet) => packet.obj.type === PacketType.SECTION_END
  )?.obj as SectionEnd | null;

  const documents = fetchStart?.documents || [];
  const isReading = Boolean(fetchStart && !fetchEnd);
  const isComplete = Boolean(fetchStart && fetchEnd);

  return { documents, isReading, isComplete };
};

export const FetchToolRenderer: MessageRenderer<FetchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  children,
}) => {
  const { documents, isReading, isComplete } =
    constructCurrentFetchState(packets);

  // Track reading timing for minimum display duration
  const [readingStartTime, setReadingStartTime] = useState<number | null>(null);
  const [shouldShowAsReading, setShouldShowAsReading] = useState(false);
  const [shouldShowAsRead, setShouldShowAsRead] = useState(isComplete);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const readTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completionHandledRef = useRef(false);

  // Track how many URLs to show
  const [urlsToShow, setUrlsToShow] = useState(INITIAL_URLS_TO_SHOW);

  // Track when reading starts (even if the reading completes instantly)
  useEffect(() => {
    if ((isReading || isComplete) && readingStartTime === null) {
      setReadingStartTime(Date.now());
      setShouldShowAsReading(true);
    }
  }, [isReading, isComplete, readingStartTime]);

  // Handle reading completion with minimum duration
  useEffect(() => {
    if (
      isComplete &&
      readingStartTime !== null &&
      !completionHandledRef.current
    ) {
      completionHandledRef.current = true;
      const elapsedTime = Date.now() - readingStartTime;
      const minimumReadingDuration = animate ? READING_MIN_DURATION_MS : 0;
      const minimumReadDuration = animate ? READ_MIN_DURATION_MS : 0;

      const handleReadingToRead = () => {
        setShouldShowAsReading(false);
        setShouldShowAsRead(true);

        readTimeoutRef.current = setTimeout(() => {
          setShouldShowAsRead(false);
          onComplete();
        }, minimumReadDuration);
      };

      if (elapsedTime >= minimumReadingDuration) {
        // Enough time has passed for reading, transition to read immediately
        handleReadingToRead();
      } else {
        // Not enough time has passed for reading, delay the transition
        const remainingTime = minimumReadingDuration - elapsedTime;
        timeoutRef.current = setTimeout(handleReadingToRead, remainingTime);
      }
    }
  }, [isComplete, readingStartTime, animate, onComplete]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      if (readTimeoutRef.current) {
        clearTimeout(readTimeoutRef.current);
      }
    };
  }, []);

  const status = useMemo(() => {
    // If we have documents to show and we're in the read state, show "Read"
    if (documents.length > 0) {
      // If we're still showing as reading (before transition), show "Reading"
      if (shouldShowAsReading) {
        return "Reading";
      }
      // Otherwise show "Read"
      return "Read";
    }

    // Handle states based on timing
    if (shouldShowAsRead) {
      return "Read";
    }
    if (isReading || isComplete || shouldShowAsReading) {
      return "Reading";
    }
    return null;
  }, [
    isReading,
    isComplete,
    shouldShowAsReading,
    shouldShowAsRead,
    documents.length,
  ]);

  // Don't render anything if fetch hasn't started
  if (documents.length === 0) {
    return children({
      icon: FiGlobe,
      status: status,
      content: <div></div>,
    });
  }

  return children({
    icon: FiGlobe,
    status,
    content: (
      <div className="flex flex-col mt-1.5">
        <div className="flex flex-col">
          <div className="text-xs font-medium mb-1 ml-1">URLs</div>
          <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
            {documents.slice(0, urlsToShow).map((doc, index) => (
              <div
                key={doc.document_id}
                className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                style={{
                  animationDelay: `${index * 30}ms`,
                  animationFillMode: "backwards",
                }}
              >
                <SourceChip2
                  icon={<FiGlobe size={10} />}
                  title={truncateString(
                    doc.semantic_identifier || doc.link || "",
                    MAX_TITLE_LENGTH
                  )}
                  onClick={() => {
                    if (doc.link) {
                      window.open(doc.link, "_blank");
                    }
                  }}
                />
              </div>
            ))}
            {/* Show a blurb if there are more URLs than we are displaying */}
            {documents.length > urlsToShow && (
              <div
                className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                style={{
                  animationDelay: `${urlsToShow * 30}ms`,
                  animationFillMode: "backwards",
                }}
              >
                <SourceChip2
                  title={`${documents.length - urlsToShow} more...`}
                  onClick={() => {
                    setUrlsToShow((prevUrls) =>
                      Math.min(prevUrls + URLS_PER_EXPANSION, documents.length)
                    );
                  }}
                />
              </div>
            )}
          </div>

          {/* If no documents, show a loading state */}
          {documents.length === 0 && <BlinkingDot />}
        </div>
      </div>
    ),
  });
};
