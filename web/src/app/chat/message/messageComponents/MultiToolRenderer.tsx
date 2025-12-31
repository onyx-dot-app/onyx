import { useState, useMemo, useEffect, JSX } from "react";
import {
  FiCheckCircle,
  FiChevronRight,
  FiChevronLeft,
  FiCircle,
  FiGitBranch,
  FiXCircle,
} from "react-icons/fi";
import {
  Packet,
  PacketType,
  SearchToolPacket,
  StopReason,
} from "@/app/chat/services/streamingModels";
import { FullChatState, RendererResult } from "./interfaces";
import { RendererComponent } from "./renderMessageComponent";
import { isToolPacket } from "../../services/packetUtils";
import { useToolDisplayTiming } from "./hooks/useToolDisplayTiming";
import { STANDARD_TEXT_COLOR } from "./constants";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import {
  getToolIcon,
  getToolName,
  hasToolError,
  isToolComplete,
} from "./toolDisplayHelpers";
import {
  SourceRetrievalStepRenderer,
  ReadDocumentsStepRenderer,
  constructCurrentSearchState,
} from "./renderers/SearchToolRenderer";
import { SvgChevronDown, SvgChevronDownSmall, SvgXCircle } from "@opal/icons";
import { LoadingSpinner } from "../../chat_search/LoadingSpinner";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

enum DisplayType {
  REGULAR = "regular",
  SEARCH_STEP_1 = "search-step-1",
  SEARCH_STEP_2 = "search-step-2",
}

type DisplayItem = {
  key: string;
  type: DisplayType;
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
  isLoading,
  isCancelled,
}: {
  icon: ((props: { size: number }) => JSX.Element) | null;
  content: JSX.Element | string;
  status: string | JSX.Element | null;
  isLastItem: boolean;
  isLoading?: boolean;
  isCancelled?: boolean;
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
              <div
                className={cn(isLoading && !isCancelled && "text-shimmer-base")}
              >
                {icon({ size: 14 })}
              </div>
            ) : (
              <FiCircle className="w-2 h-2 fill-current text-text-300" />
            )}
          </div>
        </div>
        <div className={cn("flex-1", !isLastItem && "pb-4")}>
          <Text
            as="p"
            text02
            className={cn(
              "text-sm mb-1",
              isLoading && !isCancelled && "loading-text"
            )}
          >
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
  stopReason,
  shouldStopShimmering,
  handleToolComplete,
}: {
  items: DisplayItem[];
  chatState: FullChatState;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  shouldStopShimmering: boolean;
  handleToolComplete: (turnIndex: number, tabIndex: number) => void;
}) {
  const [selectedTabIndex, setSelectedTabIndex] = useState(0);
  const [isExpanded, setIsExpanded] = useState(true);

  const toolTabs = (() => {
    const seen = new Set<number>();
    const tabs: {
      tab_index: number;
      name: string;
      icon: JSX.Element;
      packets: Packet[];
      isComplete: boolean;
      hasError: boolean;
      isCancelled: boolean;
    }[] = [];
    items.forEach((item) => {
      if (!seen.has(item.tab_index)) {
        seen.add(item.tab_index);
        // Check if this tool is complete using the helper that handles research agents properly
        const toolComplete = isToolComplete(item.packets);
        const hasError = hasToolError(item.packets);
        // Check if generation was cancelled by user (via stopReason prop)
        const isCancelled = stopReason === StopReason.USER_CANCELLED;
        tabs.push({
          tab_index: item.tab_index,
          name: getToolName(item.packets),
          icon: getToolIcon(item.packets),
          packets: item.packets,
          isComplete: toolComplete,
          hasError,
          isCancelled,
        });
      }
    });
    return tabs.sort((a, b) => a.tab_index - b.tab_index);
  })();

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
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {/* Fork/branch icon to indicate parallel execution */}
          <div className="flex-shrink-0 flex items-center justify-center w-5 h-5">
            <FiGitBranch className="w-4 h-4 text-text-400" />
          </div>

          {/* Tab buttons container */}
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
                      {isLoading && <LoadingSpinner size="small" />}
                      {tab.isComplete && !isLoading && tab.hasError && (
                        <FiXCircle
                          className={cn(
                            "w-3 h-3",
                            isActive && isExpanded
                              ? "text-red-300"
                              : "text-red-500"
                          )}
                        />
                      )}
                      {tab.isCancelled && !isLoading && !tab.hasError && (
                        <SvgXCircle
                          size={12}
                          className={cn(
                            isActive && isExpanded
                              ? "text-white opacity-70"
                              : "text-text-400"
                          )}
                        />
                      )}
                      {tab.isComplete &&
                        !isLoading &&
                        !tab.hasError &&
                        !tab.isCancelled && (
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
          <SimpleTooltip
            tooltip="Previous"
            side="top"
            disabled={!canGoPrevious || !isExpanded}
          >
            <button
              onClick={goToPreviousTab}
              disabled={!canGoPrevious || !isExpanded}
              className={cn(
                "p-1 rounded transition-colors",
                canGoPrevious && isExpanded
                  ? "hover:bg-background-tint-02 active:bg-background-tint-00"
                  : "opacity-30 cursor-not-allowed"
              )}
              aria-label="Previous tab"
            >
              <FiChevronLeft className="w-4 h-4" />
            </button>
          </SimpleTooltip>
          <SimpleTooltip
            tooltip="Next"
            side="top"
            disabled={!canGoNext || !isExpanded}
          >
            <button
              onClick={goToNextTab}
              disabled={!canGoNext || !isExpanded}
              className={cn(
                "p-1 rounded transition-colors",
                canGoNext && isExpanded
                  ? "hover:bg-background-tint-02 active:bg-background-tint-00"
                  : "opacity-30 cursor-not-allowed"
              )}
              aria-label="Next tab"
            >
              <FiChevronRight className="w-4 h-4" />
            </button>
          </SimpleTooltip>

          {/* Collapse/expand button */}
          <SimpleTooltip
            tooltip={isExpanded ? "Collapse" : "Expand"}
            side="top"
          >
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex-shrink-0 p-1 rounded hover:bg-background-tint-02 active:bg-background-tint-00 transition-colors ml-0.5"
              aria-label={isExpanded ? "Collapse" : "Expand"}
              aria-expanded={isExpanded}
            >
              <SvgChevronDown
                className={cn(
                  "w-4 h-4 stroke-text-400 transition-transform duration-150 ease-in-out",
                  isExpanded && "rotate-[-180deg]"
                )}
              />
            </button>
          </SimpleTooltip>
        </div>
      </div>

      {/* Selected tab content */}
      {isExpanded && selectedToolItems.length > 0 && (
        <div
          className="mt-3"
          role="tabpanel"
          id={`tool-panel-${toolTabs[selectedTabIndex]?.tab_index}`}
          aria-labelledby={`tool-tab-${toolTabs[selectedTabIndex]?.tab_index}`}
        >
          {selectedToolItems.map((item, index) => {
            const isLastItem = index === selectedToolItems.length - 1;

            if (item.type === DisplayType.SEARCH_STEP_1) {
              return (
                <SourceRetrievalStepRenderer
                  key={item.key}
                  packets={item.packets as SearchToolPacket[]}
                  isActive={!shouldStopShimmering}
                  isCancelled={stopReason === StopReason.USER_CANCELLED}
                >
                  {(props) => (
                    <ToolItemRow
                      {...props}
                      isLastItem={isLastItem}
                      isCancelled={stopReason === StopReason.USER_CANCELLED}
                    />
                  )}
                </SourceRetrievalStepRenderer>
              );
            } else if (item.type === DisplayType.SEARCH_STEP_2) {
              return (
                <ReadDocumentsStepRenderer
                  key={item.key}
                  packets={item.packets as SearchToolPacket[]}
                  isActive={!shouldStopShimmering}
                  isCancelled={stopReason === StopReason.USER_CANCELLED}
                >
                  {(props) => (
                    <ToolItemRow
                      {...props}
                      isLastItem={isLastItem}
                      isCancelled={stopReason === StopReason.USER_CANCELLED}
                    />
                  )}
                </ReadDocumentsStepRenderer>
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
                    <ToolItemRow
                      {...props}
                      isLastItem={isLastItem}
                      isCancelled={stopReason === StopReason.USER_CANCELLED}
                    />
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
  status: string | JSX.Element | null;
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
              as="p"
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
  stopReason,
  onAllToolsDisplayed,
  isStreaming,
  expectedBranchesPerTurn,
}: {
  packetGroups: { turn_index: number; tab_index: number; packets: Packet[] }[];
  chatState: FullChatState;
  isComplete: boolean;
  isFinalAnswerComing: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  onAllToolsDisplayed?: () => void;
  isStreaming?: boolean;
  // Map of turn_index -> expected number of parallel branches (from TopLevelBranching packet)
  expectedBranchesPerTurn?: Map<number, number>;
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
          type: DisplayType.SEARCH_STEP_1,
          turn_index: group.turn_index,
          tab_index,
          packets: group.packets,
        });
        // Only add step 2 if we have results or the search is complete
        if (shouldShowSearchStep2(group.packets)) {
          items.push({
            key: `${group.turn_index}-${tab_index}-search-2`,
            type: DisplayType.SEARCH_STEP_2,
            turn_index: group.turn_index,
            tab_index,
            packets: group.packets,
          });
        }
      } else {
        // Regular tool (including deep research plan, internet search, etc.): single entry
        items.push({
          key: `${group.turn_index}-${tab_index}`,
          type: DisplayType.REGULAR,
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
    useToolDisplayTiming(
      toolGroups,
      isFinalAnswerComing,
      isComplete,
      expectedBranchesPerTurn
    );

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

  // Track completion for all tools
  // We need to call handleToolComplete when any tool completes (has SECTION_END)
  useEffect(() => {
    displayItems.forEach((item) => {
      if (
        item.type === DisplayType.SEARCH_STEP_1 ||
        item.type === DisplayType.SEARCH_STEP_2
      ) {
        // Internal search: check via searchState.isComplete
        const searchState = constructCurrentSearchState(
          item.packets as SearchToolPacket[]
        );
        if (searchState.isComplete && item.turn_index !== undefined) {
          handleToolComplete(item.turn_index, item.tab_index);
        }
      } else if (item.type === DisplayType.REGULAR) {
        // Regular tools (including web search, openUrl, research agents, etc.):
        // Use isToolComplete helper which handles research agents correctly
        const hasCompletion = isToolComplete(item.packets);
        if (hasCompletion && item.turn_index !== undefined) {
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
    if (item.type === DisplayType.SEARCH_STEP_1) {
      return (
        <SourceRetrievalStepRenderer
          key={item.key}
          packets={item.packets as SearchToolPacket[]}
          isActive={isStreaming}
          isCancelled={stopReason === StopReason.USER_CANCELLED}
        >
          {childrenCallback}
        </SourceRetrievalStepRenderer>
      );
    } else if (item.type === DisplayType.SEARCH_STEP_2) {
      return (
        <ReadDocumentsStepRenderer
          key={item.key}
          packets={item.packets as SearchToolPacket[]}
          isActive={isStreaming}
          isCancelled={stopReason === StopReason.USER_CANCELLED}
        >
          {childrenCallback}
        </ReadDocumentsStepRenderer>
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

  // Group items by turn_index and sort by turn_index
  const turnGroups = useMemo(() => {
    const grouped = new Map<number, DisplayItem[]>();
    displayItems.forEach((item) => {
      const existing = grouped.get(item.turn_index) || [];
      existing.push(item);
      grouped.set(item.turn_index, existing);
    });
    // Convert to sorted array of [turnIndex, items] pairs
    return Array.from(grouped.entries())
      .sort(([a], [b]) => a - b)
      .map(([turnIndex, items]) => ({
        turnIndex,
        items,
        hasParallelTools: new Set(items.map((item) => item.tab_index)).size > 1,
      }));
  }, [displayItems]);

  // Helper to check if a turn has parallel tools
  const turnHasParallelTools = (turnItems: DisplayItem[]): boolean => {
    const uniqueTabIndices = new Set(turnItems.map((item) => item.tab_index));
    return uniqueTabIndices.size > 1;
  };

  // If still processing, show tools progressively with timing
  if (!isComplete) {
    // Filter display items to only show those whose (turn_index, tab_index) is visible
    const itemsToDisplay = displayItems.filter((item) =>
      visibleTools.has(`${item.turn_index}-${item.tab_index}`)
    );

    if (itemsToDisplay.length === 0) {
      return null;
    }

    // Group visible items by turn_index
    const visibleTurnGroups: {
      turnIndex: number;
      items: DisplayItem[];
      hasParallelTools: boolean;
    }[] = [];
    const visibleItemsByTurn = new Map<number, DisplayItem[]>();
    itemsToDisplay.forEach((item) => {
      const existing = visibleItemsByTurn.get(item.turn_index) || [];
      existing.push(item);
      visibleItemsByTurn.set(item.turn_index, existing);
    });
    Array.from(visibleItemsByTurn.entries())
      .sort(([a], [b]) => a - b)
      .forEach(([turnIndex, items]) => {
        visibleTurnGroups.push({
          turnIndex,
          items,
          hasParallelTools: turnHasParallelTools(items),
        });
      });

    return (
      <div className="mb-4 relative border border-border-medium rounded-lg p-4 shadow">
        {/* Timeline content */}
        <div className="relative">
          <div className="flex flex-col">
            {visibleTurnGroups.map((turnGroup, turnGroupIndex) => {
              const isLastTurnGroup =
                turnGroupIndex === visibleTurnGroups.length - 1;

              // If this turn has parallel tools, render as tabs
              if (turnGroup.hasParallelTools) {
                return (
                  <div key={`turn-${turnGroup.turnIndex}`}>
                    <ParallelToolTabs
                      items={turnGroup.items}
                      chatState={chatState}
                      stopPacketSeen={stopPacketSeen}
                      stopReason={stopReason}
                      shouldStopShimmering={shouldStopShimmering}
                      handleToolComplete={handleToolComplete}
                    />
                  </div>
                );
              }

              // Single tool in this turn - render as timeline item
              const turnItems = turnGroup.items;
              return (
                <div key={`turn-${turnGroup.turnIndex}`}>
                  {turnItems.map((item, index) => {
                    const isLastItem =
                      isLastTurnGroup && index === turnItems.length - 1;

                    // Calculate loading state for this item
                    let isItemComplete = false;
                    if (
                      item.type === DisplayType.SEARCH_STEP_1 ||
                      item.type === DisplayType.SEARCH_STEP_2
                    ) {
                      const searchState = constructCurrentSearchState(
                        item.packets as SearchToolPacket[]
                      );
                      isItemComplete = searchState.isComplete;
                    } else {
                      // Use isToolComplete helper which handles research agents correctly
                      // (only looks at parent-level SECTION_END for research agents)
                      isItemComplete = isToolComplete(item.packets);
                    }
                    const isLoading = !isItemComplete && !shouldStopShimmering;

                    return (
                      <div key={item.key}>
                        {renderDisplayItem(
                          item,
                          index,
                          turnItems.length,
                          true,
                          true,
                          ({ icon, content, status }) => (
                            <ToolItemRow
                              icon={icon}
                              content={content}
                              status={status}
                              isLastItem={isLastItem}
                              isLoading={isLoading}
                              isCancelled={
                                stopReason === StopReason.USER_CANCELLED
                              }
                            />
                          )
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // If complete, show summary with toggle and render each turn group independently
  return (
    <div className="pb-4">
      {/* Summary header - clickable */}
      <div
        className="flex flex-row w-fit items-center group/StepsButton select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Text as="p" text03 className="group-hover/StepsButton:text-text-04">
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
          <div className="flex flex-col">
            {turnGroups.map((turnGroup, turnGroupIndex) => {
              const isLastTurnGroup = turnGroupIndex === turnGroups.length - 1;

              // If this turn has parallel tools, render as tabs
              if (turnGroup.hasParallelTools) {
                return (
                  <div key={`turn-${turnGroup.turnIndex}`}>
                    <ParallelToolTabs
                      items={turnGroup.items}
                      chatState={chatState}
                      stopPacketSeen={stopPacketSeen}
                      stopReason={stopReason}
                      shouldStopShimmering={true}
                      handleToolComplete={handleToolComplete}
                    />
                    {/* Connector line to next turn group or Done node */}
                    {!isLastTurnGroup && (
                      <div
                        className="w-px bg-background-tint-04 ml-[10px] h-4"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                );
              }

              // Single tool in this turn - render sequentially
              const turnItems = turnGroup.items;
              return (
                <div key={`turn-${turnGroup.turnIndex}`}>
                  {turnItems.map((item, index) => {
                    // Don't mark as last item if there are more turns or Done node follows
                    const isLastItemInTurn = index === turnItems.length - 1;
                    const isLastItem = isLastTurnGroup && isLastItemInTurn;

                    return (
                      <div key={item.key}>
                        {renderDisplayItem(
                          item,
                          index,
                          turnItems.length,
                          false,
                          true,
                          ({ icon, content, status, expandedText }) => (
                            <ExpandedToolItem
                              icon={icon}
                              content={content}
                              status={status}
                              isLastItem={false} // Always draw connector line since Done node follows
                              defaultIconColor="text-text-03"
                              expandedText={expandedText}
                            />
                          )
                        )}
                      </div>
                    );
                  })}
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
                      {toolGroups.some((group) =>
                        group.packets.some(
                          (p) => p.obj.type === PacketType.ERROR
                        )
                      ) ? (
                        <FiXCircle className="w-3 h-3 rounded-full text-red-500" />
                      ) : (
                        <FiCheckCircle className="w-3 h-3 rounded-full" />
                      )}
                    </div>
                  </div>

                  {/* Content with padding */}
                  <div className="flex-1">
                    <div className="flex mb-1">
                      <div className="text-sm">
                        {toolGroups.some((group) =>
                          group.packets.some(
                            (p) => p.obj.type === PacketType.ERROR
                          )
                        )
                          ? "Completed with errors"
                          : "Done"}
                      </div>
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
