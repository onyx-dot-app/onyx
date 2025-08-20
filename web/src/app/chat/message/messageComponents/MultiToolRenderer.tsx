import { useState, useMemo, useEffect } from "react";
import {
  FiCheck,
  FiCheckCircle,
  FiChevronDown,
  FiChevronRight,
} from "react-icons/fi";
import { Packet } from "@/app/chat/services/streamingModels";
import { FullChatState, RendererResult } from "./interfaces";
import { renderMessageComponent } from "./renderMessageComponent";
import { isToolPacket } from "../../services/packetUtils";
import { useToolDisplayTiming } from "./hooks/useToolDisplayTiming";
import { STANDARD_TEXT_COLOR } from "./constants";

// React component wrapper to avoid hook count issues in map loops
export function RendererComponent({
  packets,
  chatState,
  onComplete,
  animate,
  useShortRenderer = false,
  children,
}: {
  packets: Packet[];
  chatState: FullChatState;
  onComplete: () => void;
  animate: boolean;
  useShortRenderer?: boolean;
  children: (result: RendererResult) => JSX.Element;
}) {
  const result = renderMessageComponent(
    { packets },
    chatState,
    onComplete,
    animate,
    useShortRenderer
  );

  return children(result);
}

// Multi-tool renderer component for grouped tools
function MultiToolRenderer({
  packetGroups,
  chatState,
  isComplete,
  isFinalAnswerComing,
  onAllToolsDisplayed,
}: {
  packetGroups: { ind: number; packets: Packet[] }[];
  chatState: FullChatState;
  isComplete: boolean;
  isFinalAnswerComing: boolean;
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
      <div className="mb-4 relative border border-border-medium rounded-lg p-4">
        <div className="relative">
          {/* Show current step header when expanded */}
          {isStreamingExpanded && (
            <div className="mb-3 text-sm text-text-700">
              Step {toolsToDisplay.length} of {toolGroups.length}
            </div>
          )}
          <div>
            {toolsToDisplay.map((toolGroup, index) => {
              if (!toolGroup) return null;

              // Hide all but the latest tool when shouldShowOnlyLatest is true
              const isVisible =
                !shouldShowOnlyLatest || index === latestToolIndex;
              const isLastItem = index === toolsToDisplay.length - 1;

              return (
                <div
                  key={index}
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
                    useShortRenderer={!isStreamingExpanded}
                  >
                    {({ icon, content, status }) => {
                      // When expanded, show full renderer style similar to complete state
                      if (isStreamingExpanded) {
                        const finalIcon = icon ? icon({ size: 14 }) : null;

                        return (
                          <div className="relative">
                            {/* Connector line */}
                            {!isLastItem && (
                              <div
                                className="absolute w-px bg-background-300 z-0"
                                style={{
                                  left: "10px",
                                  top: "20px",
                                  bottom: "0",
                                }}
                              />
                            )}

                            {/* Main row with icon and content */}
                            <div
                              className={`flex items-start gap-2 ${STANDARD_TEXT_COLOR} relative z-10`}
                            >
                              {/* Icon column */}
                              <div className="flex flex-col items-center w-5">
                                <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
                                  {finalIcon}
                                </div>
                              </div>

                              {/* Content with padding */}
                              <div
                                className={`flex-1 ${
                                  !isLastItem ? "pb-3" : ""
                                }`}
                              >
                                <div className="flex mb-1">
                                  <div
                                    className={`text-sm flex items-center gap-1 ${
                                      toolsToDisplay.length > 1 && index === 0
                                        ? "cursor-pointer hover:text-text-900 transition-colors"
                                        : ""
                                    }`}
                                    onClick={
                                      toolsToDisplay.length > 1 && index === 0
                                        ? () =>
                                            setIsStreamingExpanded(
                                              !isStreamingExpanded
                                            )
                                        : undefined
                                    }
                                  >
                                    {status}
                                    {toolsToDisplay.length > 1 &&
                                      index === 0 && (
                                        <div className="ml-1 transition-transform duration-300 ease-in-out">
                                          {isStreamingExpanded ? (
                                            <FiChevronDown size={14} />
                                          ) : (
                                            <FiChevronRight size={14} />
                                          )}
                                        </div>
                                      )}
                                  </div>
                                </div>

                                <div className="text-xs text-text-600">
                                  {content}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      }

                      // Short renderer style (original streaming view)
                      return (
                        <div className={`relative ${STANDARD_TEXT_COLOR}`}>
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
                            className={`text-sm flex items-center gap-1 loading-text ${
                              toolsToDisplay.length > 1 && isLastItem
                                ? "cursor-pointer hover:text-text-900 transition-colors"
                                : ""
                            }`}
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
                              <div className="ml-1 transition-transform duration-300 ease-in-out">
                                {isStreamingExpanded ? (
                                  <FiChevronDown size={14} />
                                ) : (
                                  <FiChevronRight size={14} />
                                )}
                              </div>
                            )}
                          </div>

                          <div
                            className={`relative z-10 mt-1 text-xs text-text-600 ${
                              !isLastItem ? "mb-3" : ""
                            }`}
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
    <div className="relative pb-1">
      {/* Summary header - clickable */}
      <div
        className="cursor-pointer transition-colors rounded-md p-1 -m-1"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center text-text-700 hover:text-text-900">
          <div className="flex items-center gap-2">
            <span className="text-sm">{toolGroups.length} steps</span>
          </div>
          <div className="transition-transform duration-300 ease-in-out">
            {isExpanded ? (
              <FiChevronDown size={16} />
            ) : (
              <FiChevronRight size={16} />
            )}
          </div>
        </div>
      </div>

      {/* Expanded content */}
      <div
        className={`transition-all duration-300 ease-in-out overflow-hidden ${
          isExpanded ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0"
        }`}
      >
        <div
          className={`p-4 transition-transform duration-300 ease-in-out ${
            isExpanded ? "transform translate-y-0" : "transform -translate-y-2"
          }`}
        >
          <div>
            {toolGroups.map((toolGroup, index) => {
              const isLastItem = index === toolGroups.length - 1;

              return (
                <RendererComponent
                  key={index}
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
                  useShortRenderer={false}
                >
                  {({ icon, content, status }) => {
                    const finalIcon = icon ? icon({ size: 14 }) : null;

                    return (
                      <div className="relative">
                        {/* Connector line drawn BEFORE content so it's behind everything */}
                        {/* Now all tools get a connector line since we have a Done node at the end */}
                        <div
                          className="absolute w-px bg-background-300 z-0"
                          style={{
                            left: "10px", // Half of icon width (20px / 2)
                            top: "20px", // Below icon (h-5 = 20px)
                            bottom: "0", // Stop at the bottom of this container, not beyond
                          }}
                        />

                        {/* Main row with icon and content */}
                        <div
                          className={`flex items-start gap-2 ${STANDARD_TEXT_COLOR} relative z-10`}
                        >
                          {/* Icon column */}
                          <div className="flex flex-col items-center w-5">
                            {/* Icon with background to cover the line */}
                            <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
                              {finalIcon}
                            </div>
                          </div>

                          {/* Content with padding */}
                          <div
                            className={`flex-1 ${!isLastItem ? "pb-3" : ""}`}
                          >
                            {
                              <div className="flex mb-1">
                                <div className="text-sm">{status}</div>
                              </div>
                            }

                            <div className="text-xs text-text-600">
                              {content}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  }}
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
                    top: "-10px",
                    height: "20px",
                  }}
                />

                {/* Main row with icon and content */}
                <div
                  className={`flex items-start gap-2 ${STANDARD_TEXT_COLOR} relative z-10 pb-3 mt-2`}
                >
                  {/* Icon column */}
                  <div className="flex flex-col items-center w-5">
                    {/* Dot with background to cover the line */}
                    <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
                      <FiCheckCircle className="w-3 h-3 text-text-700 rounded-full" />
                    </div>
                  </div>

                  {/* Content with padding */}
                  <div className="flex-1">
                    <div className="flex mb-1">
                      <div className="text-sm text-text-700">Done</div>
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

export default MultiToolRenderer;
