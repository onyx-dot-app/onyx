import React, { useEffect, useState, useRef, useMemo } from "react";
import { FiGlobe, FiLink } from "react-icons/fi";
import { SvgXCircle } from "@opal/icons";
import {
  PacketType,
  FetchToolPacket,
  FetchToolUrls,
  FetchToolDocuments,
} from "../../../services/streamingModels";
import { MessageRenderer } from "../interfaces";
import { truncateString } from "@/lib/utils";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SourceChip2 } from "@/app/chat/components/SourceChip2";
import { BlinkingDot } from "../../BlinkingDot";
import { clearTimeoutRefs } from "../timing";

const INITIAL_URLS_TO_SHOW = 3;
const URLS_PER_EXPANSION = 5;
const MAX_TITLE_LENGTH = 25;

const READING_MIN_DURATION_MS = 1000; // 1 second minimum for "Reading" state
const READ_MIN_DURATION_MS = 1000; // 1 second minimum for "Read" state

const constructCurrentFetchState = (
  packets: FetchToolPacket[]
): {
  urls: string[];
  documents: OnyxDocument[];
  hasStarted: boolean;
  isLoading: boolean;
  isComplete: boolean;
} => {
  // Check for fetch tool packets in the 3-stage sequence
  const startPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_START
  );
  const urlsPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_URLS
  )?.obj as FetchToolUrls | undefined;
  const documentsPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_DOCUMENTS
  )?.obj as FetchToolDocuments | undefined;
  const sectionEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );

  const urls = urlsPacket?.urls || [];
  const documents = documentsPacket?.documents || [];
  const hasStarted = Boolean(startPacket);
  const isLoading = hasStarted && !documentsPacket;
  const isComplete = Boolean(startPacket && sectionEnd);

  return { urls, documents, hasStarted, isLoading, isComplete };
};

export const FetchToolRenderer: MessageRenderer<FetchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  children,
}) => {
  const { urls, documents, hasStarted, isLoading, isComplete } =
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
    if ((isLoading || isComplete) && readingStartTime === null) {
      setReadingStartTime(Date.now());
      setShouldShowAsReading(true);
    }
  }, [isLoading, isComplete, readingStartTime]);

  // Handle reading completion with minimum duration
  useEffect(() => {
    if (
      isComplete &&
      readingStartTime !== null &&
      !completionHandledRef.current
    ) {
      completionHandledRef.current = true;

      // If stopped, skip intermediate states and complete immediately
      if (stopPacketSeen) {
        // Clear any pending timeouts
        clearTimeoutRefs([timeoutRef, readTimeoutRef]);

        // Skip "Read" state, go directly to completion
        setShouldShowAsReading(false);
        setShouldShowAsRead(false);
        onComplete();
        return;
      }

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
  }, [isComplete, readingStartTime, animate, onComplete, stopPacketSeen]);

  // Cleanup timeouts when stopped
  useEffect(() => {
    if (stopPacketSeen) {
      const hadPendingTimeout = clearTimeoutRefs(
        [timeoutRef, readTimeoutRef],
        true
      );

      // Reset states to prevent flickering
      setShouldShowAsReading(false);
      setShouldShowAsRead(false);
      // If we cleared a pending timeout and completion is ready, call onComplete immediately
      // This handles the case where STOP is pressed during the read-delay, canceling the only path to onComplete
      if (hadPendingTimeout && isComplete && completionHandledRef.current) {
        onComplete();
      }
    }
  }, [stopPacketSeen, isComplete, onComplete]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      clearTimeoutRefs([timeoutRef, readTimeoutRef]);
    };
  }, []);

  const status = useMemo(() => {
    // Always use present continuous form
    if (
      isLoading ||
      isComplete ||
      shouldShowAsReading ||
      shouldShowAsRead ||
      documents.length > 0
    ) {
      return "Reading";
    }
    return null;
  }, [
    isLoading,
    isComplete,
    shouldShowAsReading,
    shouldShowAsRead,
    documents.length,
  ]);

  // Don't render anything if fetch hasn't started
  if (!hasStarted) {
    return children({
      icon: FiLink,
      status: null,
      content: <div></div>,
    });
  }

  // Show documents if available, otherwise fall back to URLs from the tool call
  const displayDocuments = documents.length > 0;
  const displayUrls = !displayDocuments && isComplete && urls.length > 0;

  return children({
    icon: FiLink,
    status,
    content: (
      <div className="flex flex-col mt-1.5">
        <div className="flex flex-col">
          <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
            {displayDocuments ? (
              <>
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
                          Math.min(
                            prevUrls + URLS_PER_EXPANSION,
                            documents.length
                          )
                        );
                      }}
                    />
                  </div>
                )}
              </>
            ) : displayUrls ? (
              <>
                {urls.slice(0, urlsToShow).map((url, index) => (
                  <div
                    key={url}
                    className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                    style={{
                      animationDelay: `${index * 30}ms`,
                      animationFillMode: "backwards",
                    }}
                  >
                    <SourceChip2
                      icon={<FiGlobe size={10} />}
                      title={truncateString(url, MAX_TITLE_LENGTH)}
                      onClick={() => {
                        window.open(url, "_blank");
                      }}
                    />
                  </div>
                ))}
                {urls.length > urlsToShow && (
                  <div
                    className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                    style={{
                      animationDelay: `${urlsToShow * 30}ms`,
                      animationFillMode: "backwards",
                    }}
                  >
                    <SourceChip2
                      title={`${urls.length - urlsToShow} more...`}
                      onClick={() => {
                        setUrlsToShow((prevUrls) =>
                          Math.min(prevUrls + URLS_PER_EXPANSION, urls.length)
                        );
                      }}
                    />
                  </div>
                )}
              </>
            ) : // Show X icon if cancelled, otherwise show blinking dot for loading state
            stopPacketSeen ? (
              <SvgXCircle size={14} className="text-text-400" />
            ) : (
              <BlinkingDot />
            )}
          </div>
        </div>
      </div>
    ),
  });
};
