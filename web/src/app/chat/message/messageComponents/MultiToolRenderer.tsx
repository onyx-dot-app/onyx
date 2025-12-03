import { useState, useMemo, useEffect, JSX } from "react";
import {
  FiCheckCircle,
  FiChevronDown,
  FiChevronRight,
  FiCircle,
} from "react-icons/fi";
import {
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/chat/services/streamingModels";
import { FullChatState, RendererResult } from "./interfaces";
import { RendererComponent } from "./renderMessageComponent";
import { isToolPacket, isSearchToolPacket } from "../../services/packetUtils";
import { useToolDisplayTiming } from "./hooks/useToolDisplayTiming";
import { STANDARD_TEXT_COLOR } from "./constants";
import Text from "@/refresh-components/texts/Text";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import { cn } from "@/lib/utils";
import {
  SearchToolStep1Renderer,
  SearchToolStep2Renderer,
  constructCurrentSearchState,
} from "./renderers/SearchToolRendererV2";

// Type for display items - can be regular tool or search step
type DisplayItem = {
  key: string;
  type: "regular" | "search-step-1" | "search-step-2";
  turn_index: number;
  packets: Packet[];
};

// Helper to check if a tool group is an internal search (not internet search)
function isInternalSearchToolGroup(packets: Packet[]): boolean {
  const hasSearchStart = packets.some(
    (p) => p.obj.type === PacketType.SEARCH_TOOL_START
  );
  if (!hasSearchStart) return false;

  const searchState = constructCurrentSearchState(
    packets as SearchToolPacket[]
  );
  return !searchState.isInternetSearch;
}

// Helper to check if search step 2 should be visible (has results or is complete)
function shouldShowSearchStep2(packets: Packet[]): boolean {
  const searchState = constructCurrentSearchState(
    packets as SearchToolPacket[]
  );
  return searchState.hasResults || searchState.isComplete;
}

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
          <div className="flex mb-1">
            <Text
              text02
              className={cn(
                "text-sm flex items-center gap-1",
                showClickableToggle &&
                  "cursor-pointer hover:text-text-900 transition-colors"
              )}
              onClick={showClickableToggle ? onToggleClick : undefined}
            >
              {status}
            </Text>
          </div>

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

// Helper function to check if a tool group has a SECTION_END packet (indicating completion)
function hasSectionEnd(packets: Packet[]): boolean {
  return packets.some((packet) => packet.obj.type === PacketType.SECTION_END);
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
  packetGroups: { turn_index: number; packets: Packet[] }[];
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
      (group) => group.packets[0] && isToolPacket(group.packets[0], false)
    );
  }, [packetGroups]);

  // Transform tool groups into display items, splitting internal search tools into two steps
  const displayItems = useMemo((): DisplayItem[] => {
    const items: DisplayItem[] = [];

    toolGroups.forEach((group) => {
      if (isInternalSearchToolGroup(group.packets)) {
        // Internal search: split into two steps
        items.push({
          key: `${group.turn_index}-search-1`,
          type: "search-step-1",
          turn_index: group.turn_index,
          packets: group.packets,
        });
        // Only add step 2 if we have results or the search is complete
        if (shouldShowSearchStep2(group.packets)) {
          items.push({
            key: `${group.turn_index}-search-2`,
            type: "search-step-2",
            turn_index: group.turn_index,
            packets: group.packets,
          });
        }
      } else {
        // Regular tool (or internet search): single entry
        items.push({
          key: `${group.turn_index}`,
          type: "regular",
          turn_index: group.turn_index,
          packets: group.packets,
        });
      }
    });

    return items;
  }, [toolGroups]);

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

  // Track completion for internal search tools
  // We need to call handleToolComplete when a search tool completes
  useEffect(() => {
    displayItems.forEach((item) => {
      if (item.type === "search-step-1" || item.type === "search-step-2") {
        const searchState = constructCurrentSearchState(
          item.packets as SearchToolPacket[]
        );
        if (searchState.isComplete && item.turn_index !== undefined) {
          handleToolComplete(item.turn_index);
        }
      }
    });
  }, [displayItems, handleToolComplete]);

  // Helper to render a display item (either regular tool or search step)
  const renderDisplayItem = (
    item: DisplayItem,
    index: number,
    totalItems: number,
    isStreaming: boolean,
    isVisible: boolean,
    childrenCallback: (result: RendererResult) => JSX.Element
  ) => {
    if (item.type === "search-step-1") {
      return (
        <SearchToolStep1Renderer
          key={item.key}
          packets={item.packets as SearchToolPacket[]}
          isActive={isStreaming}
        >
          {childrenCallback}
        </SearchToolStep1Renderer>
      );
    } else if (item.type === "search-step-2") {
      return (
        <SearchToolStep2Renderer
          key={item.key}
          packets={item.packets as SearchToolPacket[]}
          isActive={isStreaming}
        >
          {childrenCallback}
        </SearchToolStep2Renderer>
      );
    } else {
      // Regular tool - use RendererComponent
      return (
        <RendererComponent
          key={item.key}
          packets={item.packets}
          chatState={chatState}
          onComplete={() => {
            if (item.turn_index !== undefined) {
              handleToolComplete(item.turn_index);
            }
          }}
          animate
          stopPacketSeen={stopPacketSeen}
          useShortRenderer={isStreaming && !isStreamingExpanded}
        >
          {childrenCallback}
        </RendererComponent>
      );
    }
  };

  // If still processing, show tools progressively with timing
  if (!isComplete) {
    // Filter display items to only show those whose turn_index is visible
    const itemsToDisplay = displayItems.filter((item) =>
      visibleTools.has(item.turn_index)
    );

    if (itemsToDisplay.length === 0) {
      return null;
    }

    // Show only the latest item visually when collapsed, but render all for completion tracking
    const shouldShowOnlyLatest =
      !isStreamingExpanded && itemsToDisplay.length > 1;
    const latestItemIndex = itemsToDisplay.length - 1;

    return (
      <div className="mb-4 relative border border-border-medium rounded-lg p-4 shadow">
        <div className="relative">
          <div>
            {itemsToDisplay.map((item, index) => {
              // Hide all but the latest item when shouldShowOnlyLatest is true
              const isVisible =
                !shouldShowOnlyLatest || index === latestItemIndex;
              const isLastItem = index === itemsToDisplay.length - 1;

              return (
                <div
                  key={item.key}
                  style={{ display: isVisible ? "block" : "none" }}
                >
                  {renderDisplayItem(
                    item,
                    index,
                    itemsToDisplay.length,
                    true,
                    isVisible,
                    ({ icon, content, status, expandedText }) => {
                      // When expanded, show full renderer style similar to complete state
                      if (isStreamingExpanded) {
                        return (
                          <ExpandedToolItem
                            icon={icon}
                            content={content}
                            status={status}
                            isLastItem={isLastItem}
                            showClickableToggle={
                              itemsToDisplay.length > 1 && index === 0
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
                              "text-base flex items-center gap-1 mb-2",
                              itemsToDisplay.length > 1 &&
                                isLastItem &&
                                "cursor-pointer hover:text-text-900 transition-colors"
                            )}
                            onClick={
                              itemsToDisplay.length > 1 && isLastItem
                                ? () =>
                                    setIsStreamingExpanded(!isStreamingExpanded)
                                : undefined
                            }
                          >
                            {icon ? (
                              <span className="text-shimmer-base">
                                {icon({ size: 14 })}
                              </span>
                            ) : null}
                            <span className="loading-text">{status}</span>
                            {itemsToDisplay.length > 1 && isLastItem && (
                              <span className="ml-1 text-shimmer-base">
                                {isStreamingExpanded ? (
                                  <FiChevronDown size={14} />
                                ) : (
                                  <FiChevronRight size={14} />
                                )}
                              </span>
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
                    }
                  )}
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
          {displayItems.length} steps
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
          "transition-all duration-300 ease-in-out overflow-hidden",
          isExpanded
            ? "max-h-[1000px] overflow-y-auto opacity-100"
            : "max-h-0 opacity-0"
        )}
      >
        <div
          className={cn(
            "p-4 transition-transform duration-300 ease-in-out",
            isExpanded ? "transform translate-y-0" : "transform"
          )}
        >
          <div>
            {displayItems.map((item, index) => {
              // Don't mark as last item if we're going to show the Done node
              const isLastItem = false; // Always draw connector line since Done node follows

              return (
                <div key={item.key}>
                  {renderDisplayItem(
                    item,
                    index,
                    displayItems.length,
                    false,
                    true,
                    ({ icon, content, status, expandedText }) => (
                      <ExpandedToolItem
                        icon={icon}
                        content={content}
                        status={status}
                        isLastItem={isLastItem}
                        defaultIconColor="text-text-03"
                        expandedText={expandedText}
                      />
                    )
                  )}
                </div>
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
