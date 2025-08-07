import {
  Packet,
  MessageStart,
  MessageDelta,
  PacketType,
  ToolPacket,
} from "../../services/streamingModels";
import { FullChatState, RendererResult } from "./interfaces";
import { findRenderer, renderMessageComponent } from "./renderMessageComponent";
import { IconType } from "react-icons";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { CopyButton } from "@/components/CopyButton";
import { LikeFeedback, DislikeFeedback } from "@/components/icons/icons";
import { HoverableIcon } from "@/components/Hoverable";
import {
  CustomTooltip,
  TooltipGroup,
} from "@/components/tooltip/CustomTooltip";
import { useMemo, useRef, useState, useEffect } from "react";
import { copyAll, handleCopy } from "../copyingUtils";
import RegenerateOption from "../../components/RegenerateOption";
import { MessageSwitcher } from "../MessageSwitcher";
import { BlinkingDot } from "../BlinkingDot";
import { STANDARD_TEXT_COLOR } from "./constants";
import { FiChevronRight, FiChevronDown } from "react-icons/fi";
import {
  getTextContent,
  groupPacketsByInd,
  isFinalAnswerComing,
  isStreamingComplete,
  isToolPacket,
} from "./packetUtils";
import { useMessageSwitching } from "./hooks/useMessageSwitching";
import { useToolDisplayTiming } from "./hooks/useToolDisplayTiming";

// React component wrapper to avoid hook count issues in map loops
function RendererComponent({
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
  onAllToolsDisplayed,
}: {
  packetGroups: { ind: number; packets: ToolPacket[] }[];
  chatState: FullChatState;
  isComplete: boolean;
  onAllToolsDisplayed?: () => void;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  const toolGroups = useMemo(() => {
    return packetGroups.filter(
      (group) => group.packets[0] && isToolPacket(group.packets[0])
    );
  }, [packetGroups]);

  // Use the custom hook to manage tool display timing
  const { visibleTools, allToolsDisplayed, handleToolComplete } =
    useToolDisplayTiming(toolGroups, isComplete);

  // Notify parent when all tools are displayed
  useEffect(() => {
    if (allToolsDisplayed && onAllToolsDisplayed) {
      onAllToolsDisplayed();
    }
  }, [allToolsDisplayed, onAllToolsDisplayed]);

  // If still processing, show tools progressively with timing
  if (!isComplete) {
    // Get the tools to display based on visibleTools
    const toolsToDisplay = toolGroups.filter((group) =>
      visibleTools.has(group.ind)
    );

    if (toolsToDisplay.length === 0) {
      return null;
    }

    // Show only the latest tool visually, but render all for completion tracking
    const shouldShowOnlyLatest = !isExpanded && toolsToDisplay.length > 1;
    const latestToolIndex = toolsToDisplay.length - 1;

    return (
      <div className="mb-4 relative border border-border-sidebar-border rounded-lg p-4">
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
                    useShortRenderer={true}
                  >
                    {({ icon, content, status }) => {
                      return (
                        <div className="relative">
                          {/* Connector line for non-last items */}
                          {!isLastItem && isVisible && (
                            <div
                              className="absolute w-px bg-gray-300 dark:bg-gray-600 z-0"
                              style={{
                                left: "10px",
                                top: "24px",
                                bottom: "-12px",
                              }}
                            />
                          )}

                          <div className="text-sm text-gray-600 dark:text-gray-400 flex items-center gap-1">
                            {icon ? icon({ size: 14 }) : null}
                            {status}
                          </div>

                          <div
                            className={`${STANDARD_TEXT_COLOR} relative z-10 mt-1 ${
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
        <div className="flex items-center">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Thought for 1m 21s
            </span>
          </div>
          <div className="text-gray-400 transition-transform duration-300 ease-in-out">
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
                        {!isLastItem && (
                          <div
                            className="absolute w-px bg-gray-300 dark:bg-gray-600 z-0"
                            style={{
                              left: "10px", // Half of icon width (20px / 2)
                              top: "20px", // Below icon (h-5 = 20px)
                              bottom: "0", // Stop at the bottom of this container, not beyond
                            }}
                          />
                        )}

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
                              <div className="flex mt-0.5 mb-1">
                                <div className="text-xs text-gray-600 dark:text-gray-400">
                                  {status}
                                </div>
                              </div>
                            }

                            {content}
                          </div>
                        </div>
                      </div>
                    );
                  }}
                </RendererComponent>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function SimpleMessage({
  rawPackets,
  chatState,
  messageId,
  otherMessagesCanSwitchTo,
  onMessageSelection,
}: {
  rawPackets: Packet[];
  chatState: FullChatState;
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (messageId: number) => void;
}) {
  const markdownRef = useRef<HTMLDivElement>(null);
  const [isRegenerateDropdownVisible, setIsRegenerateDropdownVisible] =
    useState(false);

  const [allToolsFullyDisplayed, setAllToolsFullyDisplayed] = useState(
    isFinalAnswerComing(rawPackets)
  );
  const [displayComplete, setDisplayComplete] = useState(
    isStreamingComplete(rawPackets)
  );

  // Message switching logic
  const {
    currentMessageInd,
    includeMessageSwitcher,
    getPreviousMessage,
    getNextMessage,
  } = useMessageSwitching({
    messageId,
    otherMessagesCanSwitchTo,
    onMessageSelection,
  });

  const groupedPackets = useMemo(() => {
    return groupPacketsByInd(rawPackets);
  }, [rawPackets.length]);

  console.log("allToolsFullyDisplayed", allToolsFullyDisplayed);

  // Return a list of rendered message components, one for each ind
  return (
    <div className="py-5 ml-4 lg:px-5 relative flex">
      <div className="mx-auto w-[90%] max-w-message-max">
        <div className="lg:mr-12 mobile:ml-0 md:ml-8">
          <div className="flex items-start">
            <AssistantIcon
              className="mobile:hidden"
              size={24}
              assistant={chatState.assistant}
            />
            <div className="w-full">
              <div className="max-w-message-max break-words">
                <div className="w-full desktop:ml-4">
                  <div className="max-w-message-max break-words">
                    <div
                      ref={markdownRef}
                      className="overflow-x-visible max-w-content-max focus:outline-none cursor-text select-text"
                      onCopy={(e) => handleCopy(e, markdownRef)}
                    >
                      {groupedPackets.length === 0 ? (
                        // Show blinking dot when no content yet but message is generating
                        <BlinkingDot />
                      ) : (
                        (() => {
                          // Separate tool groups from final answer groups
                          const toolGroups = groupedPackets.filter(
                            (group) =>
                              group.packets[0] && isToolPacket(group.packets[0])
                          ) as { ind: number; packets: ToolPacket[] }[];
                          // display final answer only if all tools are fully displayed
                          const finalAnswerGroups = allToolsFullyDisplayed
                            ? groupedPackets.filter(
                                (group) =>
                                  group.packets[0] &&
                                  !isToolPacket(group.packets[0])
                              )
                            : [];

                          return (
                            <>
                              {/* Render all tool groups together using MultiToolRenderer */}
                              {toolGroups.length > 0 && (
                                <MultiToolRenderer
                                  packetGroups={toolGroups}
                                  chatState={chatState}
                                  isComplete={allToolsFullyDisplayed}
                                  onAllToolsDisplayed={() =>
                                    setAllToolsFullyDisplayed(true)
                                  }
                                />
                              )}

                              {/* Render final answer groups directly using renderMessageComponent */}
                              {finalAnswerGroups.map((group) => (
                                <RendererComponent
                                  key={group.ind}
                                  packets={group.packets}
                                  chatState={chatState}
                                  onComplete={() => {
                                    // Final answer completed
                                    setDisplayComplete(true);
                                  }}
                                  animate
                                >
                                  {({ content }) => <div>{content}</div>}
                                </RendererComponent>
                              ))}
                            </>
                          );
                        })()
                      )}
                    </div>
                  </div>

                  {/* Feedback buttons - only show when streaming is complete */}
                  {chatState.handleFeedback && displayComplete && (
                    <div className="flex md:flex-row gap-x-0.5 mt-1 transition-transform duration-300 ease-in-out transform opacity-100">
                      <TooltipGroup>
                        <div className="flex justify-start w-full gap-x-0.5">
                          {includeMessageSwitcher && (
                            <div className="-mx-1 mr-auto">
                              <MessageSwitcher
                                currentPage={(currentMessageInd ?? 0) + 1}
                                totalPages={
                                  otherMessagesCanSwitchTo?.length || 0
                                }
                                handlePrevious={() => {
                                  const prevMessage = getPreviousMessage();
                                  if (
                                    prevMessage !== undefined &&
                                    onMessageSelection
                                  ) {
                                    onMessageSelection(prevMessage);
                                  }
                                }}
                                handleNext={() => {
                                  const nextMessage = getNextMessage();
                                  if (
                                    nextMessage !== undefined &&
                                    onMessageSelection
                                  ) {
                                    onMessageSelection(nextMessage);
                                  }
                                }}
                              />
                            </div>
                          )}
                        </div>
                        <CustomTooltip showTick line content="Copy">
                          <CopyButton
                            copyAllFn={() =>
                              copyAll(getTextContent(rawPackets), markdownRef)
                            }
                          />
                        </CustomTooltip>

                        <CustomTooltip showTick line content="Good response">
                          <HoverableIcon
                            icon={<LikeFeedback size={16} />}
                            onClick={() => chatState.handleFeedback("like")}
                          />
                        </CustomTooltip>

                        <CustomTooltip showTick line content="Bad response">
                          <HoverableIcon
                            icon={<DislikeFeedback size={16} />}
                            onClick={() => chatState.handleFeedback("dislike")}
                          />
                        </CustomTooltip>

                        {chatState.regenerate && (
                          <CustomTooltip
                            disabled={isRegenerateDropdownVisible}
                            showTick
                            line
                            content="Regenerate"
                          >
                            <RegenerateOption
                              onDropdownVisibleChange={
                                setIsRegenerateDropdownVisible
                              }
                              selectedAssistant={chatState.assistant}
                              regenerate={chatState.regenerate}
                              overriddenModel={chatState.overriddenModel}
                            />
                          </CustomTooltip>
                        )}
                      </TooltipGroup>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
