import { useState, useMemo, useEffect } from "react";
import {
  FiCheckCircle,
  FiChevronDown,
  FiChevronRight,
  FiCircle,
} from "react-icons/fi";
import { Packet } from "@/app/chat/services/streamingModels";
import { FullChatState, RendererResult } from "./interfaces";
import { RendererComponent } from "./renderMessageComponent";
import { isToolPacket } from "../../services/packetUtils";
import { useToolDisplayTiming } from "./hooks/useToolDisplayTiming";
import { STANDARD_TEXT_COLOR } from "./constants";
import Text from "@/refresh-components/texts/Text";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import { cn } from "@/lib/utils";

// Shared component for expanded tool rendering
function ExpandedToolItem({
  icon,
  content,
  status,
  isLastItem,
  showClickableToggle = false,
  onToggleClick,
  defaultIconColor = "text-text-300",
  expandedText,
}: {
  icon: ((props: { size: number }) => JSX.Element) | null;
  content: JSX.Element | string;
  status: string | null;
  isLastItem: boolean;
  showClickableToggle?: boolean;
  onToggleClick?: () => void;
  defaultIconColor?: string;
  expandedText?: JSX.Element | string;
}) {
  const finalIcon = icon ? (
    icon({ size: 14 })
  ) : (
    <FiCircle className={cn("w-2 h-2 fill-current", defaultIconColor)} />
  );

  return (
    <div className="relative">
      {/* Connector line */}
      {!isLastItem && (
        <div
          className="absolute w-px bg-background-tint-04 z-0"
          style={{
            left: "10px",
            top: "20px",
            bottom: "0",
          }}
        />
      )}

      {/* Main row with icon and content */}
      <div
        className={cn(
          "flex items-start gap-2",
          STANDARD_TEXT_COLOR,
          "relative z-10"
        )}
      >
        {/* Icon column */}
        <div className="flex flex-col items-center w-5">
          <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
            {finalIcon}
          </div>
        </div>

        {/* Content with padding */}
        <div className={cn("flex-1", !isLastItem && "pb-4")}>
          {status && !expandedText && (
            <div className="flex">
              <div
                className={cn(
                  "text-sm flex items-center gap-1",
                  showClickableToggle &&
                    "cursor-pointer hover:text-text-900 transition-colors"
                )}
                onClick={showClickableToggle ? onToggleClick : undefined}
              >
                {status}
              </div>
            </div>
          )}

          <div
            className={cn(
              expandedText ? "text-sm" : "text-xs text-text-600",
              expandedText && STANDARD_TEXT_COLOR
            )}
          >
            {expandedText || content}
          </div>
        </div>
      </div>
    </div>
  );
}

// React component wrapper to avoid hook count issues in map loops

// Multi-tool renderer component for grouped tools
export default function MultiToolRenderer({
  packetGroups,
  chatState,
  isComplete,
  isFinalAnswerComing,
  stopPacketSeen,
  onAllToolsDisplayed,
}: {
  packetGroups: { ind: number; packets: Packet[] }[];
  chatState: FullChatState;
  isComplete: boolean;
  isFinalAnswerComing: boolean;
  stopPacketSeen: boolean;
  onAllToolsDisplayed?: () => void;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isStreamingExpanded, setIsStreamingExpanded] = useState(false);

  const toolGroups = useMemo(() => {
    return packetGroups.filter(
      (group) => group.packets[0] && isToolPacket(group.packets[0])
    );
  }, [packetGroups]);

  // Use the custom hook to manage tool display timing
  const { visibleTools, allToolsDisplayed, handleToolComplete } =
    useToolDisplayTiming(toolGroups, isFinalAnswerComing, isComplete);

  // Notify parent when all tools are displayed
  useEffect(() => {
    if (allToolsDisplayed && onAllToolsDisplayed) {
      onAllToolsDisplayed();
    }
  }, [allToolsDisplayed, onAllToolsDisplayed]);

  // Preserve expanded state when transitioning from streaming to complete
  useEffect(() => {
    if (isComplete && isStreamingExpanded) {
      setIsExpanded(true);
    }
  }, [isComplete, isStreamingExpanded]);

  // If still processing, show tools progressively with timing
  if (!isComplete) {
    // Get the tools to display based on visibleTools
    const toolsToDisplay = toolGroups.filter((group) =>
      visibleTools.has(group.ind)
    );

    if (toolsToDisplay.length === 0) {
      return null;
    }

    // Show only the latest tool visually when collapsed, but render all for completion tracking
    const shouldShowOnlyLatest =
      !isStreamingExpanded && toolsToDisplay.length > 1;
    const latestToolIndex = toolsToDisplay.length - 1;

    return (
      <div className="mb-4 relative border border-border-medium rounded-lg p-4 shadow">
        <div className="relative">
          <div>
            {toolsToDisplay.map((toolGroup, index) => {
              if (!toolGroup) return null;

              // Hide all but the latest tool when shouldShowOnlyLatest is true
              const isVisible =
                !shouldShowOnlyLatest || index === latestToolIndex;
              const isLastItem = index === toolsToDisplay.length - 1;

              return (
                <div
                  key={toolGroup.ind}
                  style={{ display: isVisible ? "block" : "none" }}
                >
                  <RendererComponent
                    packets={toolGroup.packets}
                    chatState={chatState}
                    onComplete={() => {
                      // When a tool completes rendering, track it in the hook
                      const toolInd = toolGroup.ind;
                      if (toolInd !== undefined) {
                        handleToolComplete(toolInd);
                      }
                    }}
                    animate
                    stopPacketSeen={stopPacketSeen}
                    useShortRenderer={!isStreamingExpanded}
                  >
                    {({ icon, content, status, expandedText }) => {
                      // When expanded, show full renderer style similar to complete state
                      if (isStreamingExpanded) {
                        return (
                          <ExpandedToolItem
                            icon={icon}
                            content={content}
                            status={status}
                            isLastItem={isLastItem}
                            showClickableToggle={
                              toolsToDisplay.length > 1 && index === 0
                            }
                            onToggleClick={() =>
                              setIsStreamingExpanded(!isStreamingExpanded)
                            }
                            expandedText={expandedText}
                          />
                        );
                      }

                      // Short renderer style (original streaming view)
                      return (
                        <div className={cn("relative", STANDARD_TEXT_COLOR)}>
                          {/* Connector line for non-last items */}
                          {!isLastItem && isVisible && (
                            <div
                              className="absolute w-px z-0"
                              style={{
                                left: "10px",
                                top: "24px",
                                bottom: "-12px",
                              }}
                            />
                          )}

                          <div
                            className={cn(
                              "text-base flex items-center gap-1 loading-text mb-2",
                              toolsToDisplay.length > 1 &&
                                isLastItem &&
                                "cursor-pointer hover:text-text-900 transition-colors"
                            )}
                            onClick={
                              toolsToDisplay.length > 1 && isLastItem
                                ? () =>
                                    setIsStreamingExpanded(!isStreamingExpanded)
                                : undefined
                            }
                          >
                            {icon ? icon({ size: 14 }) : null}
                            {status}
                            {toolsToDisplay.length > 1 && isLastItem && (
                              <div className="ml-1">
                                {isStreamingExpanded ? (
                                  <FiChevronDown size={14} />
                                ) : (
                                  <FiChevronRight size={14} />
                                )}
                              </div>
                            )}
                          </div>

                          <div
                            className={cn(
                              "relative z-10 text-sm text-text-600",
                              !isLastItem && "mb-3"
                            )}
                          >
                            {content}
                          </div>
                        </div>
                      );
                    }}
                  </RendererComponent>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // If complete, show summary with toggle
  return (
    <div className="pb-1">
      {/* Summary header - clickable */}
      <div
        className="flex flex-row w-fit items-center group/StepsButton select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Text text03 className="group-hover/StepsButton:text-text-04">
          {toolGroups.length} steps
        </Text>
        <SvgChevronDownSmall
          className={cn(
            "w-[1rem] h-[1rem] stroke-text-03 group-hover/StepsButton:stroke-text-04 transition-transform duration-150 ease-in-out",
            !isExpanded && "rotate-[-90deg]"
          )}
        />
      </div>

      {/* Expanded content */}
      <div
        className={cn(
          "transition-all duration-300 ease-in-out",
          isExpanded
            ? "max-h-[2000px] opacity-100"
            : "max-h-0 opacity-0 invisible"
        )}
      >
        <div
          className={cn(
            "p-4 transition-transform duration-300 ease-in-out",
            isExpanded ? "transform translate-y-0" : "transform"
          )}
        >
          <div>
            {toolGroups.map((toolGroup, index) => {
              // Don't mark as last item if we're going to show the Done node
              const isLastItem = false; // Always draw connector line since Done node follows

              return (
                <RendererComponent
                  key={toolGroup.ind}
                  packets={toolGroup.packets}
                  chatState={chatState}
                  onComplete={() => {
                    // When a tool completes rendering, track it in the hook
                    const toolInd = toolGroup.ind;
                    if (toolInd !== undefined) {
                      handleToolComplete(toolInd);
                    }
                  }}
                  animate
                  stopPacketSeen={stopPacketSeen}
                  useShortRenderer={false}
                >
                  {({ icon, content, status, expandedText }) => (
                    <ExpandedToolItem
                      icon={icon}
                      content={content}
                      status={status}
                      isLastItem={isLastItem}
                      defaultIconColor="text-text-03"
                      expandedText={expandedText}
                    />
                  )}
                </RendererComponent>
              );
            })}

            {/* Done node at the bottom - only show after all tools are displayed */}
            {allToolsDisplayed && (
              <div className="relative">
                {/* Connector line from previous tool */}
                <div
                  className="absolute w-px bg-background-300 z-0"
                  style={{
                    left: "10px",
                    top: "-12px",
                    height: "32px",
                  }}
                />

                {/* Main row with icon and content */}
                <div
                  className={cn(
                    "flex items-start gap-2",
                    STANDARD_TEXT_COLOR,
                    "relative z-10 pb-3"
                  )}
                >
                  {/* Icon column */}
                  <div className="flex flex-col items-center w-5">
                    {/* Dot with background to cover the line */}
                    <div
                      className="
                        flex-shrink-0 
                        flex 
                        items-center 
                        justify-center 
                        w-5 
                        h-5 
                        bg-background 
                        rounded-full
                      "
                    >
                      <FiCheckCircle className="w-3 h-3 rounded-full" />
                    </div>
                  </div>

                  {/* Content with padding */}
                  <div className="flex-1">
                    <div className="flex mb-1">
                      <div className="text-sm">Done</div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
