import React, {
  useRef,
  useState,
  useEffect,
  useCallback,
  RefObject,
} from "react";
import {
  Packet,
  PacketType,
  CitationInfo,
  SearchToolDocumentsDelta,
  StreamingCitation,
  FetchToolDocuments,
  TopLevelBranching,
  StopReason,
  Stop,
} from "@/app/chat/services/streamingModels";
import { CitationMap } from "@/app/chat/interfaces";
import { FullChatState } from "@/app/chat/message/messageComponents/interfaces";
import { FeedbackType } from "@/app/chat/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import CitedSourcesToggle from "@/app/chat/message/messageComponents/CitedSourcesToggle";
import { TooltipGroup } from "@/components/tooltip/CustomTooltip";
import {
  useChatSessionStore,
  useDocumentSidebarVisible,
  useSelectedNodeForDocDisplay,
  useCurrentChatState,
} from "@/app/chat/stores/useChatSessionStore";
import {
  handleCopy,
  convertMarkdownTablesToTsv,
} from "@/app/chat/message/copyingUtils";
import MessageSwitcher from "@/app/chat/message/MessageSwitcher";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import {
  getTextContent,
  isActualToolCallPacket,
  isDisplayPacket,
  isFinalAnswerComing,
  isStreamingComplete,
  isToolPacket,
} from "@/app/chat/services/packetUtils";
import { removeThinkingTokens } from "@/app/chat/services/thinkingTokens";
import { useMessageSwitching } from "@/app/chat/message/messageComponents/hooks/useMessageSwitching";
import MultiToolRenderer from "@/app/chat/message/messageComponents/MultiToolRenderer";
import { RendererComponent } from "@/app/chat/message/messageComponents/renderMessageComponent";
import { parseToolKey } from "@/app/chat/message/messageComponents/toolDisplayHelpers";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import IconButton from "@/refresh-components/buttons/IconButton";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { parseLlmDescriptor } from "@/lib/llm/utils";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { Message } from "@/app/chat/interfaces";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import FeedbackModal, {
  FeedbackModalProps,
} from "../../components/modal/FeedbackModal";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFeedbackController } from "../../hooks/useFeedbackController";
import { SvgThumbsDown, SvgThumbsUp } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import { useTripleClickSelect } from "@/hooks/useTripleClickSelect";

// Type for the regeneration factory function passed from ChatUI
export type RegenerationFactory = (regenerationRequest: {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}) => (modelOverride: LlmDescriptor) => Promise<void>;

export interface AIMessageProps {
  rawPackets: Packet[];
  chatState: FullChatState;
  nodeId: number;
  messageId?: number;
  currentFeedback?: FeedbackType | null;
  llmManager: LlmManager | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;
  // Stable regeneration callback - takes (parentMessage) and returns a function that takes (modelOverride)
  onRegenerate?: RegenerationFactory;
  // Parent message needed to construct regeneration request
  parentMessage?: Message | null;
}

// TODO: Consider more robust comparisons:
// - `rawPackets.length` assumes packets are append-only. Could compare the last
//   packet or use a shallow comparison if packets can be modified in place.
// - `chatState.docs`, `chatState.citations`, and `otherMessagesCanSwitchTo` use
//   reference equality. Shallow array/object comparison would be more robust if
//   these are recreated with the same values.
function arePropsEqual(prev: AIMessageProps, next: AIMessageProps): boolean {
  return (
    prev.nodeId === next.nodeId &&
    prev.messageId === next.messageId &&
    prev.currentFeedback === next.currentFeedback &&
    prev.rawPackets.length === next.rawPackets.length &&
    prev.chatState.assistant?.id === next.chatState.assistant?.id &&
    prev.chatState.docs === next.chatState.docs &&
    prev.chatState.citations === next.chatState.citations &&
    prev.chatState.overriddenModel === next.chatState.overriddenModel &&
    prev.chatState.researchType === next.chatState.researchType &&
    prev.otherMessagesCanSwitchTo === next.otherMessagesCanSwitchTo &&
    prev.onRegenerate === next.onRegenerate &&
    prev.parentMessage?.messageId === next.parentMessage?.messageId &&
    prev.llmManager?.isLoadingProviders === next.llmManager?.isLoadingProviders
    // Skip: chatState.regenerate, chatState.setPresentingDocument,
    //       most of llmManager, onMessageSelection (function/object props)
  );
}

const AIMessage = React.memo(function AIMessage({
  rawPackets,
  chatState,
  nodeId,
  messageId,
  currentFeedback,
  llmManager,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  onRegenerate,
  parentMessage,
}: AIMessageProps) {
  const markdownRef = useRef<HTMLDivElement>(null);
  const finalAnswerRef = useRef<HTMLDivElement>(null);
  const handleTripleClick = useTripleClickSelect(markdownRef);
  const { popup, setPopup } = usePopup();
  const { handleFeedbackChange } = useFeedbackController({ setPopup });

  // Get the global chat state to know if we're currently streaming
  const globalChatState = useCurrentChatState();

  const modal = useCreateModal();
  const [feedbackModalProps, setFeedbackModalProps] =
    useState<FeedbackModalProps | null>(null);

  // Helper to check if feedback button should be in transient state
  const isFeedbackTransient = useCallback(
    (feedbackType: "like" | "dislike") => {
      const hasCurrentFeedback = currentFeedback === feedbackType;
      if (!modal.isOpen) return hasCurrentFeedback;

      const isModalForThisFeedback =
        feedbackModalProps?.feedbackType === feedbackType;
      const isModalForThisMessage = feedbackModalProps?.messageId === messageId;

      return (
        hasCurrentFeedback || (isModalForThisFeedback && isModalForThisMessage)
      );
    },
    [currentFeedback, modal, feedbackModalProps, messageId]
  );

  // Handler for feedback button clicks with toggle logic
  const handleFeedbackClick = useCallback(
    async (clickedFeedback: "like" | "dislike") => {
      if (!messageId) {
        console.error("Cannot provide feedback - message has no messageId");
        return;
      }

      // Toggle logic
      if (currentFeedback === clickedFeedback) {
        // Clicking same button - remove feedback
        await handleFeedbackChange(messageId, null);
      }

      // Clicking like (will automatically clear dislike if it was active).
      // Check if we need modal for positive feedback.
      else if (clickedFeedback === "like") {
        const predefinedOptions =
          process.env.NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS;
        if (predefinedOptions && predefinedOptions.trim()) {
          // Open modal for positive feedback
          setFeedbackModalProps({
            feedbackType: "like",
            messageId,
          });
          modal.toggle(true);
        } else {
          // No modal needed - just submit like (this replaces any existing feedback)
          await handleFeedbackChange(messageId, "like");
        }
      }

      // Clicking dislike (will automatically clear like if it was active).
      // Always open modal for dislike.
      else {
        setFeedbackModalProps({
          feedbackType: "dislike",
          messageId,
        });
        modal.toggle(true);
      }
    },
    [messageId, currentFeedback, chatState, modal]
  );

  const [finalAnswerComing, _setFinalAnswerComing] = useState(
    isFinalAnswerComing(rawPackets) || isStreamingComplete(rawPackets)
  );
  const setFinalAnswerComing = (value: boolean) => {
    _setFinalAnswerComing(value);
    finalAnswerComingRef.current = value;
  };

  const [displayComplete, _setDisplayComplete] = useState(
    isStreamingComplete(rawPackets)
  );
  const setDisplayComplete = (value: boolean) => {
    _setDisplayComplete(value);
    displayCompleteRef.current = value;
  };

  const [stopPacketSeen, _setStopPacketSeen] = useState(
    isStreamingComplete(rawPackets)
  );
  const setStopPacketSeen = (value: boolean) => {
    _setStopPacketSeen(value);
    stopPacketSeenRef.current = value;
  };

  // Track the reason for stopping (e.g., user cancelled)
  const [stopReason, setStopReason] = useState<StopReason | undefined>(
    undefined
  );
  const stopReasonRef = useRef<StopReason | undefined>(undefined);

  // Incremental packet processing state
  const lastProcessedIndexRef = useRef<number>(0);
  const citationsRef = useRef<StreamingCitation[]>([]);
  const seenCitationDocIdsRef = useRef<Set<string>>(new Set());
  // CitationMap for immediate rendering: citation_num -> document_id
  const citationMapRef = useRef<CitationMap>({});
  const documentMapRef = useRef<Map<string, OnyxDocument>>(new Map());
  // Use composite key "turn_index-tab_index" for grouping to support parallel tool calls
  const groupedPacketsMapRef = useRef<Map<string, Packet[]>>(new Map());
  const groupedPacketsRef = useRef<
    { turn_index: number; tab_index: number; packets: Packet[] }[]
  >([]);
  const finalAnswerComingRef = useRef<boolean>(isFinalAnswerComing(rawPackets));
  const displayCompleteRef = useRef<boolean>(isStreamingComplete(rawPackets));
  const stopPacketSeenRef = useRef<boolean>(isStreamingComplete(rawPackets));
  // Track composite keys "turn_index-tab_index" for graceful SECTION_END injection
  const seenGroupKeysRef = useRef<Set<string>>(new Set());
  const groupKeysWithSectionEndRef = useRef<Set<string>>(new Set());
  // Track expected parallel branches per turn_index from TopLevelBranching packets
  const expectedBranchesRef = useRef<Map<number, number>>(new Map());

  // Reset incremental state when switching messages or when stream resets
  const resetState = () => {
    lastProcessedIndexRef.current = 0;
    citationsRef.current = [];
    seenCitationDocIdsRef.current = new Set();
    citationMapRef.current = {};
    documentMapRef.current = new Map();
    groupedPacketsMapRef.current = new Map();
    groupedPacketsRef.current = [];
    finalAnswerComingRef.current = isFinalAnswerComing(rawPackets);
    displayCompleteRef.current = isStreamingComplete(rawPackets);
    stopPacketSeenRef.current = isStreamingComplete(rawPackets);
    stopReasonRef.current = undefined;
    setStopReason(undefined);
    seenGroupKeysRef.current = new Set();
    groupKeysWithSectionEndRef.current = new Set();
    expectedBranchesRef.current = new Map();
  };
  useEffect(() => {
    resetState();
  }, [nodeId]);

  // If the upstream replaces packets with a shorter list (reset), clear state
  if (lastProcessedIndexRef.current > rawPackets.length) {
    resetState();
  }

  // Helper function to check if a packet group has meaningful content
  const hasContentPackets = (packets: Packet[]): boolean => {
    const contentPacketTypes = [
      PacketType.MESSAGE_START,
      PacketType.SEARCH_TOOL_START,
      PacketType.IMAGE_GENERATION_TOOL_START,
      PacketType.PYTHON_TOOL_START,
      PacketType.CUSTOM_TOOL_START,
      PacketType.FETCH_TOOL_START,
      PacketType.REASONING_START,
      PacketType.DEEP_RESEARCH_PLAN_START,
      PacketType.RESEARCH_AGENT_START,
    ];
    return packets.some((packet) =>
      contentPacketTypes.includes(packet.obj.type as PacketType)
    );
  };

  // Helper function to inject synthetic SECTION_END packet
  const injectSectionEnd = (groupKey: string) => {
    if (groupKeysWithSectionEndRef.current.has(groupKey)) {
      return; // Already has SECTION_END
    }

    const { turn_index, tab_index } = parseToolKey(groupKey);

    const syntheticPacket: Packet = {
      placement: { turn_index, tab_index },
      obj: { type: PacketType.SECTION_END },
    };

    const existingGroup = groupedPacketsMapRef.current.get(groupKey);
    if (existingGroup) {
      existingGroup.push(syntheticPacket);
    }
    groupKeysWithSectionEndRef.current.add(groupKey);
  };

  // Process only the new packets synchronously for this render
  if (rawPackets.length > lastProcessedIndexRef.current) {
    for (let i = lastProcessedIndexRef.current; i < rawPackets.length; i++) {
      const packet = rawPackets[i];
      if (!packet) continue;

      // Handle TopLevelBranching packets - these tell us how many parallel branches to expect
      if (packet.obj.type === PacketType.TOP_LEVEL_BRANCHING) {
        const branchingPacket = packet.obj as TopLevelBranching;
        expectedBranchesRef.current.set(
          packet.placement.turn_index,
          branchingPacket.num_parallel_branches
        );
        // Don't add this packet to any group, it's just metadata
        continue;
      }

      const currentTurnIndex = packet.placement.turn_index;
      const currentTabIndex = packet.placement.tab_index ?? 0;
      const currentGroupKey = `${currentTurnIndex}-${currentTabIndex}`;
      // If we see a new turn_index (not just tab_index), inject SECTION_END for previous groups
      // We only inject SECTION_END when moving to a completely new turn, not for parallel tools
      const previousTurnIndices = new Set(
        Array.from(seenGroupKeysRef.current).map(
          (key) => parseToolKey(key).turn_index
        )
      );
      const isNewTurnIndex = !previousTurnIndices.has(currentTurnIndex);

      if (isNewTurnIndex && seenGroupKeysRef.current.size > 0) {
        Array.from(seenGroupKeysRef.current).forEach((prevGroupKey) => {
          if (!groupKeysWithSectionEndRef.current.has(prevGroupKey)) {
            injectSectionEnd(prevGroupKey);
          }
        });
      }

      // Track this group key
      seenGroupKeysRef.current.add(currentGroupKey);

      // Track SECTION_END and ERROR packets (both indicate completion)
      if (
        packet.obj.type === PacketType.SECTION_END ||
        packet.obj.type === PacketType.ERROR
      ) {
        groupKeysWithSectionEndRef.current.add(currentGroupKey);
      }

      // Grouping by composite key (turn_index, tab_index)
      const existingGroup = groupedPacketsMapRef.current.get(currentGroupKey);
      if (existingGroup) {
        existingGroup.push(packet);
      } else {
        groupedPacketsMapRef.current.set(currentGroupKey, [packet]);
      }

      // Citations - handle CITATION_INFO packets
      if (packet.obj.type === PacketType.CITATION_INFO) {
        // Individual citation packet from backend streaming
        const citationInfo = packet.obj as CitationInfo;
        // Add to citation map immediately for rendering
        citationMapRef.current[citationInfo.citation_number] =
          citationInfo.document_id;
        // Also add to citations array for CitedSourcesToggle
        if (!seenCitationDocIdsRef.current.has(citationInfo.document_id)) {
          seenCitationDocIdsRef.current.add(citationInfo.document_id);
          citationsRef.current.push({
            citation_num: citationInfo.citation_number,
            document_id: citationInfo.document_id,
          });
        }
      }

      // Documents from tool deltas
      if (packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA) {
        const docDelta = packet.obj as SearchToolDocumentsDelta;
        if (docDelta.documents) {
          for (const doc of docDelta.documents) {
            if (doc.document_id) {
              documentMapRef.current.set(doc.document_id, doc);
            }
          }
        }
      } else if (packet.obj.type === PacketType.FETCH_TOOL_DOCUMENTS) {
        const fetchDocuments = packet.obj as FetchToolDocuments;
        if (fetchDocuments.documents) {
          for (const doc of fetchDocuments.documents) {
            if (doc.document_id) {
              documentMapRef.current.set(doc.document_id, doc);
            }
          }
        }
      }

      // check if final answer is coming
      if (
        packet.obj.type === PacketType.MESSAGE_START ||
        packet.obj.type === PacketType.MESSAGE_DELTA ||
        packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START ||
        packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA ||
        packet.obj.type === PacketType.PYTHON_TOOL_START ||
        packet.obj.type === PacketType.PYTHON_TOOL_DELTA
      ) {
        // Set both ref and state to trigger re-render and show message content
        if (!finalAnswerComingRef.current) {
          setFinalAnswerComing(true);
        }
        finalAnswerComingRef.current = true;
      }

      if (packet.obj.type === PacketType.STOP && !stopPacketSeenRef.current) {
        setStopPacketSeen(true);
        // Extract and store the stop reason
        const stopPacket = packet.obj as Stop;
        setStopReason(stopPacket.stop_reason);
        stopReasonRef.current = stopPacket.stop_reason;
        // Inject SECTION_END for all group keys that don't have one
        Array.from(seenGroupKeysRef.current).forEach((groupKey) => {
          if (!groupKeysWithSectionEndRef.current.has(groupKey)) {
            injectSectionEnd(groupKey);
          }
        });
      }

      // handles case where we get a Message packet from Claude, and then tool
      // calling packets. We use isActualToolCallPacket instead of isToolPacket
      // to exclude reasoning packets - reasoning is just the model thinking,
      // not an actual tool call that would produce new content. If we reset
      // finalAnswerComing for reasoning packets, the message content won't
      // display until page refresh.
      if (
        finalAnswerComingRef.current &&
        !stopPacketSeenRef.current &&
        isActualToolCallPacket(packet)
      ) {
        setFinalAnswerComing(false);
        setDisplayComplete(false);
      }
    }

    // Rebuild the grouped packets array sorted by turn_index, then tab_index
    // Clone packet arrays to ensure referential changes so downstream memo hooks update
    // Filter out empty groups (groups with only SECTION_END and no content)
    groupedPacketsRef.current = Array.from(
      groupedPacketsMapRef.current.entries()
    )
      .map(([key, packets]) => {
        const { turn_index, tab_index } = parseToolKey(key);
        return {
          turn_index,
          tab_index,
          packets: [...packets],
        };
      })
      .filter(({ packets }) => hasContentPackets(packets))
      .sort((a, b) => {
        if (a.turn_index !== b.turn_index) {
          return a.turn_index - b.turn_index;
        }
        return a.tab_index - b.tab_index;
      });

    lastProcessedIndexRef.current = rawPackets.length;
  }

  const citations = citationsRef.current;
  const documentMap = documentMapRef.current;
  // Get the incrementally built citation map for immediate rendering
  const streamingCitationMap = citationMapRef.current;

  // Create a chatState that uses streaming citations for immediate rendering
  // This merges the prop citations with streaming citations, preferring streaming ones
  const effectiveChatState: FullChatState = {
    ...chatState,
    citations: {
      ...chatState.citations,
      ...streamingCitationMap,
    },
  };

  // Use store for document sidebar
  const documentSidebarVisible = useDocumentSidebarVisible();
  const selectedMessageForDocDisplay = useSelectedNodeForDocDisplay();
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const updateCurrentSelectedNodeForDocDisplay = useChatSessionStore(
    (state) => state.updateCurrentSelectedNodeForDocDisplay
  );

  // Message switching logic
  const {
    currentMessageInd,
    includeMessageSwitcher,
    getPreviousMessage,
    getNextMessage,
  } = useMessageSwitching({
    nodeId,
    otherMessagesCanSwitchTo,
    onMessageSelection,
  });

  const groupedPackets = groupedPacketsRef.current;

  // Return a list of rendered message components, one for each ind
  return (
    <>
      {popup}

      <modal.Provider>
        <FeedbackModal {...feedbackModalProps!} />
      </modal.Provider>

      <div
        // for e2e tests
        data-testid={displayComplete ? "onyx-ai-message" : undefined}
        className="flex items-start pb-5 md:pt-5"
      >
        <AgentAvatar agent={chatState.assistant} size={24} />
        {/* w-full ensures the MultiToolRenderer non-expanded state takes up the full width */}
        <div className="max-w-message-max break-words pl-4 w-full">
          <div
            ref={markdownRef}
            className="overflow-x-visible max-w-content-max focus:outline-none select-text cursor-text"
            onMouseDown={handleTripleClick}
            onCopy={(e) => {
              if (markdownRef.current) {
                handleCopy(e, markdownRef as RefObject<HTMLDivElement>);
              }
            }}
          >
            {groupedPackets.length === 0 ? (
              // Show blinking dot when no content yet, or stopped message if user cancelled
              stopReason === StopReason.USER_CANCELLED ? (
                <Text as="p" secondaryBody text04>
                  User has stopped generation
                </Text>
              ) : (
                <BlinkingDot addMargin />
              )
            ) : (
              (() => {
                // Simple split: tools vs non-tools
                const toolGroups = groupedPackets.filter(
                  (group) =>
                    group.packets[0] && isToolPacket(group.packets[0], false)
                );

                // Non-tools include messages AND image generation
                const displayGroups =
                  finalAnswerComing || toolGroups.length === 0
                    ? groupedPackets.filter(
                        (group) =>
                          group.packets[0] && isDisplayPacket(group.packets[0])
                      )
                    : [];

                return (
                  <>
                    {/* Render tool groups in multi-tool renderer */}
                    {toolGroups.length > 0 && (
                      <MultiToolRenderer
                        packetGroups={toolGroups}
                        chatState={effectiveChatState}
                        isComplete={finalAnswerComing}
                        isFinalAnswerComing={finalAnswerComingRef.current}
                        stopPacketSeen={stopPacketSeen}
                        stopReason={stopReason}
                        isStreaming={globalChatState === "streaming"}
                        onAllToolsDisplayed={() => setFinalAnswerComing(true)}
                        expectedBranchesPerTurn={expectedBranchesRef.current}
                      />
                    )}

                    {/* Render all display groups (messages + image generation) in main area */}
                    <div ref={finalAnswerRef}>
                      {displayGroups.map((displayGroup, index) => (
                        <RendererComponent
                          key={`${displayGroup.turn_index}-${displayGroup.tab_index}`}
                          packets={displayGroup.packets}
                          chatState={effectiveChatState}
                          onComplete={() => {
                            // if we've reverted to final answer not coming, don't set display complete
                            // this happens when using claude and a tool calling packet comes after
                            // some message packets
                            // Only mark complete on the last display group
                            if (
                              finalAnswerComingRef.current &&
                              index === displayGroups.length - 1
                            ) {
                              setDisplayComplete(true);
                            }
                          }}
                          animate={false}
                          stopPacketSeen={stopPacketSeen}
                          stopReason={stopReason}
                        >
                          {({ content }) => <div>{content}</div>}
                        </RendererComponent>
                      ))}
                      {/* Show stopped message when user cancelled and no display content */}
                      {displayGroups.length === 0 &&
                        stopReason === StopReason.USER_CANCELLED && (
                          <Text as="p" secondaryBody text04>
                            User has stopped generation
                          </Text>
                        )}
                    </div>
                  </>
                );
              })()
            )}
          </div>

          {/* Feedback buttons - only show when streaming is complete */}
          {stopPacketSeen && displayComplete && (
            <div className="flex md:flex-row justify-between items-center w-full mt-1 transition-transform duration-300 ease-in-out transform opacity-100">
              <TooltipGroup>
                <div className="flex items-center gap-x-0.5">
                  {includeMessageSwitcher && (
                    <div className="-mx-1">
                      <MessageSwitcher
                        currentPage={(currentMessageInd ?? 0) + 1}
                        totalPages={otherMessagesCanSwitchTo?.length || 0}
                        handlePrevious={() => {
                          const prevMessage = getPreviousMessage();
                          if (prevMessage !== undefined && onMessageSelection) {
                            onMessageSelection(prevMessage);
                          }
                        }}
                        handleNext={() => {
                          const nextMessage = getNextMessage();
                          if (nextMessage !== undefined && onMessageSelection) {
                            onMessageSelection(nextMessage);
                          }
                        }}
                      />
                    </div>
                  )}

                  <CopyIconButton
                    getCopyText={() =>
                      convertMarkdownTablesToTsv(
                        removeThinkingTokens(
                          getTextContent(rawPackets)
                        ) as string
                      )
                    }
                    getHtmlContent={() =>
                      finalAnswerRef.current?.innerHTML || ""
                    }
                    tertiary
                    data-testid="AIMessage/copy-button"
                  />
                  <IconButton
                    icon={SvgThumbsUp}
                    onClick={() => handleFeedbackClick("like")}
                    tertiary
                    transient={isFeedbackTransient("like")}
                    tooltip={
                      currentFeedback === "like"
                        ? "Remove Like"
                        : "Good Response"
                    }
                    data-testid="AIMessage/like-button"
                  />
                  <IconButton
                    icon={SvgThumbsDown}
                    onClick={() => handleFeedbackClick("dislike")}
                    tertiary
                    transient={isFeedbackTransient("dislike")}
                    tooltip={
                      currentFeedback === "dislike"
                        ? "Remove Dislike"
                        : "Bad Response"
                    }
                    data-testid="AIMessage/dislike-button"
                  />

                  {onRegenerate &&
                    messageId !== undefined &&
                    parentMessage &&
                    llmManager && (
                      <div data-testid="AIMessage/regenerate">
                        <LLMPopover
                          llmManager={llmManager}
                          currentModelName={chatState.overriddenModel}
                          onSelect={(modelName) => {
                            const llmDescriptor = parseLlmDescriptor(modelName);
                            const regenerator = onRegenerate({
                              messageId,
                              parentMessage,
                            });
                            regenerator(llmDescriptor);
                          }}
                          folded
                        />
                      </div>
                    )}

                  {nodeId && (citations.length > 0 || documentMap.size > 0) && (
                    <CitedSourcesToggle
                      citations={citations}
                      documentMap={documentMap}
                      nodeId={nodeId}
                      onToggle={(toggledNodeId) => {
                        // Toggle sidebar if clicking on the same message
                        if (
                          selectedMessageForDocDisplay === toggledNodeId &&
                          documentSidebarVisible
                        ) {
                          updateCurrentDocumentSidebarVisible(false);
                          updateCurrentSelectedNodeForDocDisplay(null);
                        } else {
                          updateCurrentSelectedNodeForDocDisplay(toggledNodeId);
                          updateCurrentDocumentSidebarVisible(true);
                        }
                      }}
                    />
                  )}
                </div>
              </TooltipGroup>
            </div>
          )}
        </div>
      </div>
    </>
  );
}, arePropsEqual);

export default AIMessage;
