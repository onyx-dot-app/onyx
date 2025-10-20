import {
  Packet,
  PacketType,
  CitationDelta,
  SearchToolDelta,
  StreamingCitation,
} from "@/app/chat/services/streamingModels";
import { FullChatState } from "@/app/chat/message/messageComponents/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import CitedSourcesToggle from "@/app/chat/message/messageComponents/CitedSourcesToggle";
import { TooltipGroup } from "@/components/tooltip/CustomTooltip";
import { useMemo, useRef, useState, useEffect } from "react";
import {
  useChatSessionStore,
  useDocumentSidebarVisible,
  useSelectedNodeForDocDisplay,
} from "@/app/chat/stores/useChatSessionStore";
import { copyAll, handleCopy } from "@/app/chat/message/copyingUtils";
import MessageSwitcher from "@/app/chat/message/MessageSwitcher";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import {
  getTextContent,
  isDisplayPacket,
  isFinalAnswerComing,
  isStreamingComplete,
  isToolPacket,
} from "@/app/chat/services/packetUtils";
import { useMessageSwitching } from "@/app/chat/message/messageComponents/hooks/useMessageSwitching";
import MultiToolRenderer from "@/app/chat/message/messageComponents/MultiToolRenderer";
import { RendererComponent } from "@/app/chat/message/messageComponents/renderMessageComponent";
import { AgentIcon } from "@/refresh-components/AgentIcon";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgCopy from "@/icons/copy";
import SvgThumbsUp from "@/icons/thumbs-up";
import SvgThumbsDown from "@/icons/thumbs-down";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import LLMPopover from "@/refresh-components/LLMPopover";
import { parseLlmDescriptor } from "@/lib/llm/utils";
import { LlmManager } from "@/lib/hooks";

export interface AIMessageProps {
  rawPackets: Packet[];
  chatState: FullChatState;
  nodeId: number;
  llmManager: LlmManager | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;
}

export default function AIMessage({
  rawPackets,
  chatState,
  nodeId,
  llmManager,
  otherMessagesCanSwitchTo,
  onMessageSelection,
}: AIMessageProps) {
  const markdownRef = useRef<HTMLDivElement>(null);

  const { toggleModal } = useChatModal();

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

  // Incremental packet processing state
  const lastProcessedIndexRef = useRef<number>(0);
  const citationsRef = useRef<StreamingCitation[]>([]);
  const seenCitationDocIdsRef = useRef<Set<string>>(new Set());
  const documentMapRef = useRef<Map<string, OnyxDocument>>(new Map());
  const groupedPacketsMapRef = useRef<Map<number, Packet[]>>(new Map());
  const groupedPacketsRef = useRef<{ ind: number; packets: Packet[] }[]>([]);
  const finalAnswerComingRef = useRef<boolean>(isFinalAnswerComing(rawPackets));
  const displayCompleteRef = useRef<boolean>(isStreamingComplete(rawPackets));
  const stopPacketSeenRef = useRef<boolean>(isStreamingComplete(rawPackets));

  // Reset incremental state when switching messages or when stream resets
  const resetState = () => {
    lastProcessedIndexRef.current = 0;
    citationsRef.current = [];
    seenCitationDocIdsRef.current = new Set();
    documentMapRef.current = new Map();
    groupedPacketsMapRef.current = new Map();
    groupedPacketsRef.current = [];
    finalAnswerComingRef.current = isFinalAnswerComing(rawPackets);
    displayCompleteRef.current = isStreamingComplete(rawPackets);
    stopPacketSeenRef.current = isStreamingComplete(rawPackets);
  };
  useEffect(() => {
    resetState();
  }, [nodeId]);

  // If the upstream replaces packets with a shorter list (reset), clear state
  if (lastProcessedIndexRef.current > rawPackets.length) {
    resetState();
  }

  // Process only the new packets synchronously for this render
  if (rawPackets.length > lastProcessedIndexRef.current) {
    for (let i = lastProcessedIndexRef.current; i < rawPackets.length; i++) {
      const packet = rawPackets[i];
      if (!packet) continue;

      // Grouping by ind
      const existingGroup = groupedPacketsMapRef.current.get(packet.ind);
      if (existingGroup) {
        existingGroup.push(packet);
      } else {
        groupedPacketsMapRef.current.set(packet.ind, [packet]);
      }

      // Citations
      if (packet.obj.type === PacketType.CITATION_DELTA) {
        const citationDelta = packet.obj as CitationDelta;
        if (citationDelta.citations) {
          for (const citation of citationDelta.citations) {
            if (!seenCitationDocIdsRef.current.has(citation.document_id)) {
              seenCitationDocIdsRef.current.add(citation.document_id);
              citationsRef.current.push(citation);
            }
          }
        }
      }

      // Documents from tool deltas
      if (
        packet.obj.type === PacketType.SEARCH_TOOL_DELTA ||
        packet.obj.type === PacketType.FETCH_TOOL_START
      ) {
        const toolDelta = packet.obj as SearchToolDelta;
        if ("documents" in toolDelta && toolDelta.documents) {
          for (const doc of toolDelta.documents) {
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
        packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA
      ) {
        finalAnswerComingRef.current = true;
      }

      if (packet.obj.type === PacketType.STOP && !stopPacketSeenRef.current) {
        setStopPacketSeen(true);
      }

      // handles case where we get a Message packet from Claude, and then tool
      // calling packets
      if (
        finalAnswerComingRef.current &&
        !stopPacketSeenRef.current &&
        isToolPacket(packet, false)
      ) {
        setFinalAnswerComing(false);
        setDisplayComplete(false);
      }
    }

    // Rebuild the grouped packets array sorted by ind
    // Clone packet arrays to ensure referential changes so downstream memo hooks update
    groupedPacketsRef.current = Array.from(
      groupedPacketsMapRef.current.entries()
    )
      .map(([ind, packets]) => ({ ind, packets: [...packets] }))
      .sort((a, b) => a.ind - b.ind);

    lastProcessedIndexRef.current = rawPackets.length;
  }

  const citations = citationsRef.current;
  const documentMap = documentMapRef.current;

  // Use store for document sidebar
  const documentSidebarVisible = useDocumentSidebarVisible();
  const selectedMessageForDocDisplay = useSelectedNodeForDocDisplay();
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const updateCurrentSelectedNodeForDocDisplay = useChatSessionStore(
    (state) => state.updateCurrentSelectedNodeForDocDisplay
  );
  // Calculate unique source count
  const _uniqueSourceCount = useMemo(() => {
    const uniqueDocIds = new Set<string>();
    for (const citation of citations) {
      if (citation.document_id) {
        uniqueDocIds.add(citation.document_id);
      }
    }
    documentMap.forEach((_, docId) => {
      uniqueDocIds.add(docId);
    });
    return uniqueDocIds.size;
  }, [citations.length, documentMap.size]);

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
    <div
      // for e2e tests
      data-testid={displayComplete ? "onyx-ai-message" : undefined}
      className="py-5 ml-4 lg:px-5 relative flex"
    >
      <div className="mx-auto w-[90%] max-w-message-max">
        <div className="lg:mr-12 mobile:ml-0 md:ml-8">
          <div className="flex items-start">
            <AgentIcon agent={chatState.assistant} />
            <div className="w-full">
              <div className="max-w-message-max break-words">
                <div className="w-full desktop:ml-4">
                  <div className="max-w-message-max break-words">
                    <div
                      ref={markdownRef}
                      className="overflow-x-visible max-w-content-max focus:outline-none select-text"
                      onCopy={(e) => handleCopy(e, markdownRef)}
                    >
                      {groupedPackets.length === 0 ? (
                        // Show blinking dot when no content yet but message is generating
                        <BlinkingDot addMargin />
                      ) : (
                        (() => {
                          // Simple split: tools vs non-tools
                          const toolGroups = groupedPackets.filter(
                            (group) =>
                              group.packets[0] && isToolPacket(group.packets[0])
                          ) as { ind: number; packets: Packet[] }[];

                          // Non-tools include messages AND image generation
                          const displayGroups =
                            finalAnswerComing || toolGroups.length === 0
                              ? groupedPackets.filter(
                                  (group) =>
                                    group.packets[0] &&
                                    isDisplayPacket(group.packets[0])
                                )
                              : [];

                          const lastDisplayGroup =
                            displayGroups.length > 0
                              ? displayGroups[displayGroups.length - 1]
                              : null;

                          return (
                            <>
                              {/* Render tool groups in multi-tool renderer */}
                              {toolGroups.length > 0 && (
                                <MultiToolRenderer
                                  packetGroups={toolGroups}
                                  chatState={chatState}
                                  isComplete={finalAnswerComing}
                                  isFinalAnswerComing={
                                    finalAnswerComingRef.current
                                  }
                                  stopPacketSeen={stopPacketSeen}
                                  onAllToolsDisplayed={() =>
                                    setFinalAnswerComing(true)
                                  }
                                />
                              )}

                              {/* Render non-tool groups (messages + image generation) in main area */}
                              {lastDisplayGroup && (
                                <RendererComponent
                                  key={lastDisplayGroup.ind}
                                  packets={lastDisplayGroup.packets}
                                  chatState={chatState}
                                  onComplete={() => {
                                    // if we've reverted to final answer not coming, don't set display complete
                                    // this happens when using claude and a tool calling packet comes after
                                    // some message packets
                                    if (finalAnswerComingRef.current) {
                                      setDisplayComplete(true);
                                    }
                                  }}
                                  animate={false}
                                  stopPacketSeen={stopPacketSeen}
                                >
                                  {({ content }) => <div>{content}</div>}
                                </RendererComponent>
                              )}
                            </>
                          );
                        })()
                      )}
                    </div>
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

                          <IconButton
                            icon={SvgCopy}
                            onClick={() => copyAll(getTextContent(rawPackets))}
                            tertiary
                            tooltip="Copy"
                            data-testid="AIMessage/copy-button"
                          />
                          <IconButton
                            icon={SvgThumbsUp}
                            onClick={() =>
                              toggleModal(ModalIds.FeedbackModal, true, {
                                feedbackType: "like",
                                messageId: nodeId,
                              })
                            }
                            tertiary
                            tooltip="Good Response"
                            data-testid="AIMessage/like-button"
                          />
                          <IconButton
                            icon={SvgThumbsDown}
                            onClick={() =>
                              toggleModal(ModalIds.FeedbackModal, true, {
                                feedbackType: "dislike",
                                messageId: nodeId,
                              })
                            }
                            tertiary
                            tooltip="Bad Response"
                            data-testid="AIMessage/dislike-button"
                          />

                          {chatState.regenerate && llmManager && (
                            <div data-testid="AIMessage/regenerate">
                              <LLMPopover
                                llmManager={llmManager}
                                currentModelName={chatState.overriddenModel}
                                onSelect={(modelName) => {
                                  const llmDescriptor =
                                    parseLlmDescriptor(modelName);
                                  chatState.regenerate!(llmDescriptor);
                                }}
                                folded
                              />
                            </div>
                          )}

                          {nodeId &&
                            (citations.length > 0 || documentMap.size > 0) && (
                              <CitedSourcesToggle
                                citations={citations}
                                documentMap={documentMap}
                                nodeId={nodeId}
                                onToggle={(toggledNodeId) => {
                                  // Toggle sidebar if clicking on the same message
                                  if (
                                    selectedMessageForDocDisplay ===
                                      toggledNodeId &&
                                    documentSidebarVisible
                                  ) {
                                    updateCurrentDocumentSidebarVisible(false);
                                    updateCurrentSelectedNodeForDocDisplay(
                                      null
                                    );
                                  } else {
                                    updateCurrentSelectedNodeForDocDisplay(
                                      toggledNodeId
                                    );
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
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
