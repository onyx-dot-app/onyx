import { useState, useMemo, useEffect, JSX } from "react";
import {
  FiCheckCircle,
  FiChevronDown,
  FiChevronRight,
  FiChevronLeft,
  FiCircle,
  FiLoader,
} from "react-icons/fi";
import {
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/chat/services/streamingModels";
import { FullChatState, RendererResult } from "./interfaces";
import { RendererComponent } from "./renderMessageComponent";
import { isToolPacket } from "../../services/packetUtils";
import { useToolDisplayTiming } from "./hooks/useToolDisplayTiming";
import { STANDARD_TEXT_COLOR } from "./constants";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { getToolIcon, getToolName } from "./toolDisplayHelpers";
import {
  SearchToolStep1Renderer,
  SearchToolStep2Renderer,
  constructCurrentSearchState,
} from "./renderers/SearchToolRendererV2";
import { SvgChevronDownSmall } from "@opal/icons";

type DisplayItem = {
  key: string;
  type: "regular" | "search-step-1" | "search-step-2";
  turn_index: number;
  tab_index: number;
  packets: Packet[];
};

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

function shouldShowSearchStep2(packets: Packet[]): boolean {
  const searchState = constructCurrentSearchState(
    packets as SearchToolPacket[]
  );
  return searchState.hasResults || searchState.isComplete;
}

function ToolItemRow({
  icon,
  content,
  status,
  isLastItem,
}: {
  icon: ((props: { size: number }) => JSX.Element) | null;
  content: JSX.Element | string;
  status: string | null;
  isLastItem: boolean;
}) {
  return (
    <div className="relative">
      {!isLastItem && (
        <div
          className="absolute w-px bg-background-tint-04 z-0"
          style={{ left: "10px", top: "20px", bottom: "0" }}
        />
      )}
      <div
        className={cn(
          "flex items-start gap-2",
          STANDARD_TEXT_COLOR,
          "relative z-10"
        )}
      >
        <div className="flex flex-col items-center w-5">
          <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
            {icon ? (
              icon({ size: 14 })
            ) : (
              <FiCircle className="w-2 h-2 fill-current text-text-300" />
            )}
          </div>
        </div>
        <div className={cn("flex-1", !isLastItem && "pb-4")}>
          <Text text02 className="text-sm mb-1">
            {status}
          </Text>
          <div className="text-xs text-text-600">{content}</div>
        </div>
      </div>
    </div>
  );
}

function ParallelToolTabs({
  items,
  chatState,
  stopPacketSeen,
  shouldStopShimmering,
  handleToolComplete,
}: {
  items: DisplayItem[];
  chatState: FullChatState;
  stopPacketSeen: boolean;
  shouldStopShimmering: boolean;
  handleToolComplete: (turnIndex: number, tabIndex: number) => void;
}) {
  const [selectedTabIndex, setSelectedTabIndex] = useState(0);
  const [isExpanded, setIsExpanded] = useState(true);

  // Get unique tools (by tab_index) - each tab represents a different parallel tool
  const toolTabs = useMemo(() => {
    const seen = new Set<number>();
    const tabs: {
      tab_index: number;
      name: string;
      icon: JSX.Element;
      packets: Packet[];
      isComplete: boolean;
    }[] = [];
    items.forEach((item) => {
      if (!seen.has(item.tab_index)) {
        seen.add(item.tab_index);
        // Check if this tool is complete (has SECTION_END)
        const isComplete = item.packets.some(
          (p) => p.obj.type === PacketType.SECTION_END
        );
        tabs.push({
          tab_index: item.tab_index,
          name: getToolName(item.packets),
          icon: getToolIcon(item.packets),
          packets: item.packets,
          isComplete,
        });
      }
    });
    return tabs.sort((a, b) => a.tab_index - b.tab_index);
  }, [items]);

  // Get the selected tool's display items (may include search-step-1 and search-step-2)
  const selectedToolItems = useMemo(() => {
    const selectedTab = toolTabs[selectedTabIndex];
    if (!selectedTab) return [];
    return items.filter((item) => item.tab_index === selectedTab.tab_index);
  }, [items, toolTabs, selectedTabIndex]);

  const canGoPrevious = selectedTabIndex > 0;
  const canGoNext = selectedTabIndex < toolTabs.length - 1;

  const goToPreviousTab = () => {
    if (canGoPrevious) {
      setSelectedTabIndex(selectedTabIndex - 1);
    }
  };

  const goToNextTab = () => {
    if (canGoNext) {
      setSelectedTabIndex(selectedTabIndex + 1);
    }
  };

  if (toolTabs.length === 0) return null;

  return (
    <div className="flex flex-col pb-2">
      {/* Tab bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 flex-1 min-w-0">
          {/* Expand/collapse toggle */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1 rounded hover:bg-background-subtle-hover transition-colors flex-shrink-0"
            aria-expanded={isExpanded}
            aria-label={
              isExpanded ? "Collapse tool details" : "Expand tool details"
            }
          >
            {isExpanded ? (
              <FiChevronDown className="w-4 h-4 text-text-500" />
            ) : (
              <FiChevronRight className="w-4 h-4 text-text-500" />
            )}
          </button>

          {/* Tab buttons container with underline */}
          <div className="relative flex flex-col flex-1 min-w-0">
            {/* Tabs row */}
            <div className="flex gap-1" role="tablist" aria-label="Tool tabs">
              {toolTabs.map((tab, index) => {
                const isActive = selectedTabIndex === index;
                const isLoading = !tab.isComplete && !shouldStopShimmering;
                const tabId = `tool-tab-${tab.tab_index}`;
                const panelId = `tool-panel-${tab.tab_index}`;

                return (
                  <div
                    key={tab.tab_index}
                    className={cn("relative", isExpanded && "pb-1.5")}
                  >
                    <button
                      id={tabId}
                      role="tab"
                      aria-selected={isActive}
                      aria-controls={panelId}
                      tabIndex={isActive ? 0 : -1}
                      onClick={() => setSelectedTabIndex(index)}
                      onKeyDown={(e) => {
                        if (e.key === "ArrowRight") {
                          e.preventDefault();
                          const nextIndex = Math.min(
                            index + 1,
                            toolTabs.length - 1
                          );
                          setSelectedTabIndex(nextIndex);
                        } else if (e.key === "ArrowLeft") {
                          e.preventDefault();
                          const prevIndex = Math.max(index - 1, 0);
                          setSelectedTabIndex(prevIndex);
                        }
                      }}
                      className={cn(
                        "flex items-center gap-1.5 px-1 py-1 rounded-lg text-sm whitespace-nowrap transition-all duration-200 border",
                        isActive && isExpanded
                          ? "bg-neutral-800 dark:bg-neutral-700 border-neutral-800 dark:border-neutral-600 text-white font-medium"
                          : "bg-transparent border-border-medium text-text-500 hover:bg-background-subtle hover:border-border-strong"
                      )}
                    >
                      <span
                        className={cn(
                          isLoading && !isActive && "text-shimmer-base"
                        )}
                      >
                        {tab.icon}
                      </span>
                      <span
                        className={cn(isLoading && !isActive && "loading-text")}
                      >
                        {tab.name}
                      </span>
                      {isLoading && (
                        <FiLoader
                          className={cn(
                            "w-3 h-3 animate-spin",
                            isActive ? "text-white opacity-70" : "text-text-400"
                          )}
                        />
                      )}
                      {tab.isComplete && !isLoading && (
                        <FiCheckCircle
                          className={cn(
                            "w-3 h-3",
                            isActive && isExpanded
                              ? "text-white opacity-70"
                              : "text-text-400"
                          )}
                        />
                      )}
                    </button>
                    {/* Active indicator overlay - only for active tab when expanded */}
                    {isExpanded && (
                      <div
                        className={cn(
                          "absolute bottom-0 left-0 right-0 h-0.5 transition-colors duration-200",
                          isActive
                            ? "bg-neutral-700 dark:bg-neutral-300"
                            : "bg-transparent"
                        )}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Navigation arrows - navigate between tabs */}
        <div className="flex items-center gap-0.5 ml-2 flex-shrink-0">
          <button
            onClick={goToPreviousTab}
            disabled={!canGoPrevious}
            className={cn(
              "p-1 rounded hover:bg-background-subtle-hover transition-colors",
              !canGoPrevious && "opacity-30 cursor-not-allowed"
            )}
            aria-label="Previous tab"
          >
            <FiChevronLeft className="w-4 h-4" />
          </button>
          <button
            onClick={goToNextTab}
            disabled={!canGoNext}
            className={cn(
              "p-1 rounded hover:bg-background-subtle-hover transition-colors",
              !canGoNext && "opacity-30 cursor-not-allowed"
            )}
            aria-label="Next tab"
          >
            <FiChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Selected tab content */}
      {isExpanded && selectedToolItems.length > 0 && (
        <div
          className="mt-3 pl-6"
          role="tabpanel"
          id={`tool-panel-${toolTabs[selectedTabIndex]?.tab_index}`}
          aria-labelledby={`tool-tab-${toolTabs[selectedTabIndex]?.tab_index}`}
        >
          {selectedToolItems.map((item, index) => {
            const isLastItem = index === selectedToolItems.length - 1;

            if (item.type === "search-step-1") {
              return (
                <SearchToolStep1Renderer
                  key={item.key}
                  packets={item.packets as SearchToolPacket[]}
                  isActive={!shouldStopShimmering}
                >
                  {(props) => (
                    <ToolItemRow {...props} isLastItem={isLastItem} />
                  )}
                </SearchToolStep1Renderer>
              );
            } else if (item.type === "search-step-2") {
              return (
                <SearchToolStep2Renderer
                  key={item.key}
                  packets={item.packets as SearchToolPacket[]}
                  isActive={!shouldStopShimmering}
                >
                  {(props) => (
                    <ToolItemRow {...props} isLastItem={isLastItem} />
                  )}
                </SearchToolStep2Renderer>
              );
            } else {
              // Regular tool
              return (
                <RendererComponent
                  key={item.key}
                  packets={item.packets}
                  chatState={chatState}
                  onComplete={() =>
                    handleToolComplete(item.turn_index, item.tab_index)
                  }
                  animate
                  stopPacketSeen={stopPacketSeen}
                  useShortRenderer={false}
                >
                  {(props) => (
                    <ToolItemRow {...props} isLastItem={isLastItem} />
                  )}
                </RendererComponent>
              );
            }
          })}
        </div>
      )}
    </div>
  );
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

// Multi-tool renderer component for grouped tools
export default function MultiToolRenderer({
  packetGroups,
  chatState,
  isComplete,
  isFinalAnswerComing,
  stopPacketSeen,
  onAllToolsDisplayed,
  isStreaming,
}: {
  packetGroups: { turn_index: number; tab_index: number; packets: Packet[] }[];
  chatState: FullChatState;
  isComplete: boolean;
  isFinalAnswerComing: boolean;
  stopPacketSeen: boolean;
  onAllToolsDisplayed?: () => void;
  isStreaming?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isStreamingExpanded, setIsStreamingExpanded] = useState(false);

  const toolGroups = useMemo(() => {
    return packetGroups.filter(
      (group) => group.packets[0] && isToolPacket(group.packets[0], false)
    );
  }, [packetGroups]);

  // Stop shimmering when:
  // 1. stopPacketSeen is true (STOP packet arrived - for deep research/agent framework)
  // 2. isStreaming is false (global chat state changed to "input" - for regular searches)
  // 3. isComplete is true (all tools finished)
  const shouldStopShimmering = useMemo(() => {
    return stopPacketSeen || isStreaming === false || isComplete;
  }, [stopPacketSeen, isStreaming, isComplete]);

  // Transform tool groups into display items, splitting internal search tools into two steps
  const displayItems = useMemo((): DisplayItem[] => {
    const items: DisplayItem[] = [];

    toolGroups.forEach((group) => {
      const tab_index = group.tab_index ?? 0;
      if (isInternalSearchToolGroup(group.packets)) {
        // Internal search: split into two steps
        items.push({
          key: `${group.turn_index}-${tab_index}-search-1`,
          type: "search-step-1",
          turn_index: group.turn_index,
          tab_index,
          packets: group.packets,
        });
        // Only add step 2 if we have results or the search is complete
        if (shouldShowSearchStep2(group.packets)) {
          items.push({
            key: `${group.turn_index}-${tab_index}-search-2`,
            type: "search-step-2",
            turn_index: group.turn_index,
            tab_index,
            packets: group.packets,
          });
        }
      } else {
        // Regular tool (or internet search): single entry
        items.push({
          key: `${group.turn_index}-${tab_index}`,
          type: "regular",
          turn_index: group.turn_index,
          tab_index,
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
          handleToolComplete(item.turn_index, item.tab_index);
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
          onComplete={() => handleToolComplete(item.turn_index, item.tab_index)}
          animate
          stopPacketSeen={stopPacketSeen}
          useShortRenderer={isStreaming && !isStreamingExpanded}
        >
          {childrenCallback}
        </RendererComponent>
      );
    }
  };

  // Group items by turn_index to detect parallel tools
  const itemsByTurnIndex = useMemo(() => {
    const grouped = new Map<number, DisplayItem[]>();
    displayItems.forEach((item) => {
      const existing = grouped.get(item.turn_index) || [];
      existing.push(item);
      grouped.set(item.turn_index, existing);
    });
    return grouped;
  }, [displayItems]);

  // Check if any turn has parallel tools (multiple distinct tab_index values)
  const hasParallelTools = useMemo(() => {
    return Array.from(itemsByTurnIndex.values()).some((items) => {
      const uniqueTabIndices = new Set(items.map((item) => item.tab_index));
      return uniqueTabIndices.size > 1;
    });
  }, [itemsByTurnIndex]);

  // If still processing, show tools progressively with timing
  if (!isComplete) {
    // Filter display items to only show those whose (turn_index, tab_index) is visible
    const itemsToDisplay = displayItems.filter((item) =>
      visibleTools.has(`${item.turn_index}-${item.tab_index}`)
    );

    if (itemsToDisplay.length === 0) {
      return null;
    }

    // Check if current visible items have parallel tools
    const visibleItemsByTurn = new Map<number, DisplayItem[]>();
    itemsToDisplay.forEach((item) => {
      const existing = visibleItemsByTurn.get(item.turn_index) || [];
      existing.push(item);
      visibleItemsByTurn.set(item.turn_index, existing);
    });

    const currentTurnHasParallelTools = Array.from(
      visibleItemsByTurn.values()
    ).some((items) => {
      const uniqueTabIndices = new Set(items.map((item) => item.tab_index));
      return uniqueTabIndices.size > 1;
    });

    // If current turn has parallel tools, render with tabs
    if (currentTurnHasParallelTools) {
      return (
        <div className="mb-4 relative border border-border-medium rounded-lg p-4 shadow">
          <ParallelToolTabs
            items={itemsToDisplay}
            chatState={chatState}
            stopPacketSeen={stopPacketSeen}
            shouldStopShimmering={shouldStopShimmering}
            handleToolComplete={handleToolComplete}
          />
        </div>
      );
    }

    // Otherwise, render sequentially as before
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
                              <span
                                className={cn(
                                  // Only shimmer icon if generation NOT stopped
                                  !shouldStopShimmering && "text-shimmer-base"
                                )}
                              >
                                {icon({ size: 14 })}
                              </span>
                            ) : null}
                            <span
                              className={cn(
                                // Only shimmer if generation NOT stopped
                                !shouldStopShimmering && "loading-text"
                              )}
                            >
                              {status}
                            </span>
                            {itemsToDisplay.length > 1 && isLastItem && (
                              <span
                                className={cn(
                                  "ml-1",
                                  // Only shimmer chevron if generation NOT stopped
                                  !shouldStopShimmering && "text-shimmer-base"
                                )}
                              >
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

  // If complete and has parallel tools, show tabbed interface
  if (hasParallelTools) {
    return (
      <div className="pb-1">
        <ParallelToolTabs
          items={displayItems}
          chatState={chatState}
          stopPacketSeen={stopPacketSeen}
          shouldStopShimmering={true}
          handleToolComplete={handleToolComplete}
        />
      </div>
    );
  }

  // If complete with sequential tools only, show summary with toggle
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
