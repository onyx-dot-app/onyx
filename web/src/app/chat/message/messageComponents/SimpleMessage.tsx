import {
  Packet,
  MessageStart,
  MessageDelta,
  PacketType,
} from "../../services/streamingModels";
import { AnimationType, FullChatState } from "./interfaces";
import { renderMessageComponent } from "./renderMessageComponent";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { CopyButton } from "@/components/CopyButton";
import { LikeFeedback, DislikeFeedback } from "@/components/icons/icons";
import { HoverableIcon } from "@/components/Hoverable";
import {
  CustomTooltip,
  TooltipGroup,
} from "@/components/tooltip/CustomTooltip";
import { useMemo, useRef, useState, useCallback } from "react";
import { copyAll, handleCopy } from "../copyingUtils";
import RegenerateOption from "../../components/RegenerateOption";
import { MessageSwitcher } from "../MessageSwitcher";
import { BlinkingDot } from "../BlinkingDot";
import { STANDARD_TEXT_COLOR } from "./constants";
import { FiChevronRight, FiChevronDown } from "react-icons/fi";

// Custom hook to manage tool display timing
function useToolDisplayTiming(toolGroups: Packet[][], isComplete: boolean) {
  const [visibleToolCount, setVisibleToolCount] = useState(0);
  const [allToolsDisplayed, setAllToolsDisplayed] = useState(false);
  const lastUpdateTimeRef = useRef<number>(Date.now());
  const intervalIdRef = useRef<NodeJS.Timeout | null>(null);

  useMemo(() => {
    // Clear any existing interval when component unmounts or isComplete changes
    if (intervalIdRef.current) {
      clearInterval(intervalIdRef.current);
      intervalIdRef.current = null;
    }

    // If streaming is complete, show all tools
    if (isComplete) {
      setVisibleToolCount(toolGroups.length);
      setAllToolsDisplayed(true);
      return;
    }

    // Reset visible count if no tools
    if (toolGroups.length === 0) {
      setVisibleToolCount(0);
      setAllToolsDisplayed(true); // No tools to display, so we're "done"
      return;
    }

    // Initialize with at least one tool visible
    if (visibleToolCount === 0 && toolGroups.length > 0) {
      setVisibleToolCount(1);
      lastUpdateTimeRef.current = Date.now();
    }

    // Set up interval to check if we should show more tools
    intervalIdRef.current = setInterval(() => {
      const now = Date.now();
      const timeSinceLastUpdate = now - lastUpdateTimeRef.current;

      // If at least 5 seconds have passed and there are more tools to show
      if (timeSinceLastUpdate >= 5000 && visibleToolCount < toolGroups.length) {
        setVisibleToolCount((prev) => prev + 1);
        lastUpdateTimeRef.current = now;
      }

      // Check if we've shown all tools
      if (visibleToolCount >= toolGroups.length && toolGroups.length > 0) {
        // Wait 5 more seconds after showing the last tool before allowing final answer
        if (!allToolsDisplayed && timeSinceLastUpdate >= 5000) {
          setAllToolsDisplayed(true);
        }

        if (intervalIdRef.current && allToolsDisplayed) {
          clearInterval(intervalIdRef.current);
          intervalIdRef.current = null;
        }
      }
    }, 100); // Check every 100ms

    return () => {
      if (intervalIdRef.current) {
        clearInterval(intervalIdRef.current);
      }
    };
  }, [toolGroups.length, isComplete, visibleToolCount, allToolsDisplayed]);

  return { visibleToolCount, allToolsDisplayed };
}

// Multi-tool renderer component for grouped tools
function MultiToolRenderer({
  packets,
  chatState,
  isComplete,
  onAllToolsDisplayed,
  onToolComplete,
}: {
  packets: Packet[];
  chatState: FullChatState;
  isComplete: boolean;
  onAllToolsDisplayed?: () => void;
  onToolComplete?: (toolInd: number) => void;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Group packets by tool instance (consecutive tool start/delta/end sequences)
  const toolGroups: Packet[][] = [];
  let currentGroup: Packet[] = [];

  for (const packet of packets) {
    if (packet.obj.type === PacketType.TOOL_START) {
      // Start a new group
      if (currentGroup.length > 0) {
        toolGroups.push(currentGroup);
      }
      currentGroup = [packet];
    } else {
      // Add to current group
      currentGroup.push(packet);
    }
  }

  // Don't forget the last group
  if (currentGroup.length > 0) {
    toolGroups.push(currentGroup);
  }

  // Use the custom hook to manage tool display timing
  const { visibleToolCount, allToolsDisplayed } = useToolDisplayTiming(
    toolGroups,
    isComplete
  );

  // Notify parent when all tools are displayed
  useMemo(() => {
    if (allToolsDisplayed && onAllToolsDisplayed) {
      onAllToolsDisplayed();
    }
  }, [allToolsDisplayed, onAllToolsDisplayed]);

  // If still processing, show tools progressively with timing
  if (!isComplete) {
    // Get the tools to display based on visibleToolCount
    const toolsToDisplay = toolGroups.slice(0, visibleToolCount);

    if (toolsToDisplay.length === 0) {
      return null;
    }

    return (
      <div className="mb-4 relative border border-border-sidebar-border rounded-lg p-4">
        <div className="relative">
          <div>
            {toolsToDisplay.map((toolGroup, index) => {
              const { icon, content } = renderMessageComponent(
                { packets: toolGroup },
                chatState,
                () => {
                  // When a tool completes rendering, notify parent
                  const toolInd = toolGroup[0]?.ind;
                  if (toolInd !== undefined && onToolComplete) {
                    onToolComplete(toolInd);
                  }
                },
                AnimationType.FAST,
                true
              );

              const finalIcon = icon ? icon({ size: 14 }) : null;
              const isLastItem = index === toolsToDisplay.length - 1;

              return (
                <div key={index} className="relative">
                  {/* Connector line for non-last items */}
                  {!isLastItem && (
                    <div
                      className="absolute w-px bg-gray-300 dark:bg-gray-600 z-0"
                      style={{
                        left: "10px",
                        top: "20px",
                        bottom: "-12px",
                      }}
                    />
                  )}

                  <div
                    className={`flex items-start gap-2 ${STANDARD_TEXT_COLOR} relative z-10 ${!isLastItem ? "mb-3" : ""}`}
                  >
                    <div className="flex flex-col items-center w-5">
                      <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
                        {finalIcon}
                      </div>
                    </div>
                    <div className="flex-1">{content}</div>
                  </div>
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
              const { icon, content } = renderMessageComponent(
                { packets: toolGroup },
                chatState,
                () => {
                  // When a tool completes rendering, notify parent
                  const toolInd = toolGroup[0]?.ind;
                  if (toolInd !== undefined && onToolComplete) {
                    onToolComplete(toolInd);
                  }
                },
                AnimationType.SLOW,
                false
              );

              const finalIcon = icon ? icon({ size: 14 }) : null;
              const isLastItem = index === toolGroups.length - 1;

              return (
                <div key={index} className="relative">
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
                    <div className={`flex-1 ${!isLastItem ? "pb-3" : ""}`}>
                      {content}
                    </div>
                  </div>
                </div>
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

  // Track which tool calls have completed displaying
  const [completedToolInds, setCompletedToolInds] = useState<Set<number>>(
    new Set()
  );

  // Calculate message switching state
  const currentMessageInd = messageId
    ? otherMessagesCanSwitchTo?.indexOf(messageId)
    : undefined;

  const includeMessageSwitcher =
    currentMessageInd !== undefined &&
    onMessageSelection &&
    otherMessagesCanSwitchTo &&
    otherMessagesCanSwitchTo.length > 1;

  const getPreviousMessage = () => {
    if (
      currentMessageInd !== undefined &&
      currentMessageInd > 0 &&
      otherMessagesCanSwitchTo
    ) {
      return otherMessagesCanSwitchTo[currentMessageInd - 1];
    }
    return undefined;
  };

  const getNextMessage = () => {
    if (
      currentMessageInd !== undefined &&
      currentMessageInd < (otherMessagesCanSwitchTo?.length || 0) - 1 &&
      otherMessagesCanSwitchTo
    ) {
      return otherMessagesCanSwitchTo[currentMessageInd + 1];
    }
    return undefined;
  };

  // Group all chat packets together by ind
  const groupedChatPacketsByInd: Map<number, Packet[]> = rawPackets.reduce(
    (acc: Map<number, Packet[]>, packet) => {
      const ind = packet.ind;
      if (!acc.has(ind)) {
        acc.set(ind, []);
      }
      acc.get(ind)!.push(packet);
      return acc;
    },
    new Map()
  );

  // Helper function to check if packets are tool packets
  const isToolGroup = (packets: Packet[]) => {
    return packets.some(
      (packet) =>
        packet.obj.type === PacketType.TOOL_START ||
        packet.obj.type === PacketType.TOOL_DELTA ||
        packet.obj.type === PacketType.TOOL_END
    );
  };

  // Create smart groups that combine consecutive tool groups
  const createSmartGroups = () => {
    const sortedEntries = Array.from(groupedChatPacketsByInd.entries()).sort(
      ([a], [b]) => a - b
    );

    const smartGroups: {
      packets: Packet[];
      isToolGroup: boolean;
      inds: number[];
    }[] = [];
    let currentToolGroup: { packets: Packet[]; inds: number[] } | null = null;

    for (const [ind, packets] of sortedEntries) {
      const isThisGroupTools = isToolGroup(packets);

      if (isThisGroupTools) {
        if (currentToolGroup) {
          // Add to existing tool group
          currentToolGroup.packets.push(...packets);
          currentToolGroup.inds.push(ind);
        } else {
          // Start new tool group
          currentToolGroup = { packets: [...packets], inds: [ind] };
        }
      } else {
        // Non-tool group - finalize any pending tool group first
        if (currentToolGroup) {
          smartGroups.push({
            packets: currentToolGroup.packets,
            isToolGroup: true,
            inds: currentToolGroup.inds,
          });
          currentToolGroup = null;
        }
        // Add the non-tool group
        smartGroups.push({
          packets,
          isToolGroup: false,
          inds: [ind],
        });
      }
    }

    // Don't forget any pending tool group
    if (currentToolGroup) {
      smartGroups.push({
        packets: currentToolGroup.packets,
        isToolGroup: true,
        inds: currentToolGroup.inds,
      });
    }

    return smartGroups;
  };

  const smartGroups = createSmartGroups();

  // Check if streaming is complete (has STOP packet)
  const isStreamingComplete = rawPackets.some(
    (packet) => packet.obj.type === PacketType.STOP
  );

  const isFinalAnswerComing = rawPackets.some(
    (packet) => packet.obj.type === PacketType.MESSAGE_START
  );

  // Track whether all tools have been displayed
  const [allToolsFullyDisplayed, setAllToolsFullyDisplayed] = useState(false);

  // Callback to handle when a tool completes
  const handleToolComplete = useCallback((toolInd: number) => {
    setCompletedToolInds((prev) => new Set(prev).add(toolInd));
  }, []);

  // Filter smart groups to only show up to the last completed tool
  const getVisibleSmartGroups = useCallback(() => {
    // If streaming is complete, show everything
    if (isStreamingComplete) {
      return smartGroups;
    }

    // Find the highest index of completed tools
    let highestCompletedInd = -1;
    for (const group of smartGroups) {
      if (group.isToolGroup) {
        // Check if all tools in this group are completed
        const allIndsCompleted = group.inds.every((ind) =>
          completedToolInds.has(ind)
        );
        if (allIndsCompleted) {
          highestCompletedInd = Math.max(highestCompletedInd, ...group.inds);
        }
      }
    }

    // Return groups up to and including the last completed tool group
    const visibleGroups: typeof smartGroups = [];
    for (const group of smartGroups) {
      const maxGroupInd = Math.max(...group.inds);
      if (maxGroupInd <= highestCompletedInd) {
        visibleGroups.push(group);
      } else if (
        group.isToolGroup &&
        group.inds.some((ind) => ind <= highestCompletedInd)
      ) {
        // Include partially completed tool groups
        visibleGroups.push(group);
      }
    }

    return visibleGroups;
  }, [smartGroups, completedToolInds, isStreamingComplete]);

  const visibleSmartGroups = getVisibleSmartGroups();

  // Extract text content for copying
  const getTextContent = () => {
    return smartGroups
      .map((group) => {
        // Extract text from packets - this is a simplified approach
        return group.packets
          .map((packet) => {
            if (
              packet.obj.type === PacketType.MESSAGE_START ||
              packet.obj.type === PacketType.MESSAGE_DELTA
            ) {
              return (packet.obj as MessageStart | MessageDelta).content || "";
            }
            return "";
          })
          .join("")
          .trim();
      })
      .join("\n")
      .trim();
  };

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
                      {visibleSmartGroups.length === 0 &&
                      !isStreamingComplete ? (
                        // Show blinking dot when no content yet but message is generating
                        <BlinkingDot />
                      ) : (
                        visibleSmartGroups.map((group, index) => {
                          if (group.isToolGroup) {
                            return (
                              <div key={group.inds.join("-")}>
                                <MultiToolRenderer
                                  packets={group.packets}
                                  chatState={chatState}
                                  isComplete={isFinalAnswerComing}
                                  onAllToolsDisplayed={() =>
                                    setAllToolsFullyDisplayed(true)
                                  }
                                  onToolComplete={handleToolComplete}
                                />
                              </div>
                            );
                          } else {
                            // Non-tool groups (final answer) - show based on completion tracking
                            const { content } = renderMessageComponent(
                              { packets: group.packets },
                              chatState,
                              () => {
                                // Mark these inds as complete
                                group.inds.forEach((ind) =>
                                  handleToolComplete(ind)
                                );
                                setAllToolsFullyDisplayed(true);
                              },
                              AnimationType.FAST
                            );
                            return (
                              <div key={group.inds.join("-")}>{content}</div>
                            );
                          }
                        })
                      )}
                    </div>
                  </div>

                  {/* Feedback buttons - only show when streaming is complete */}
                  {chatState.handleFeedback && isStreamingComplete && (
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
                              copyAll(getTextContent(), markdownRef)
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
