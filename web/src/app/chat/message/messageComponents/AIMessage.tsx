import {
  Packet,
  PacketType,
  CitationDelta,
  SearchToolDelta,
  StreamingCitation,
} from "../../services/streamingModels";
import { FullChatState } from "./interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { CopyButton } from "@/components/CopyButton";
import { LikeFeedback, DislikeFeedback } from "@/components/icons/icons";
import { HoverableIcon } from "@/components/Hoverable";
import { OnyxDocument } from "@/lib/search/interfaces";
import { CitedSourcesToggle } from "./CitedSourcesToggle";
import {
  CustomTooltip,
  TooltipGroup,
} from "@/components/tooltip/CustomTooltip";
import { useMemo, useRef, useState, useEffect } from "react";
import {
  useChatSessionStore,
  useDocumentSidebarVisible,
  useSelectedNodeForDocDisplay,
} from "../../stores/useChatSessionStore";
import { copyAll, handleCopy } from "../copyingUtils";
import RegenerateOption from "../../components/RegenerateOption";
import { MessageSwitcher } from "../MessageSwitcher";
import { BlinkingDot } from "../BlinkingDot";
import {
  getTextContent,
  isDisplayPacket,
  isFinalAnswerComing,
  isStreamingComplete,
  isToolPacket,
} from "../../services/packetUtils";
import { useMessageSwitching } from "./hooks/useMessageSwitching";
import MultiToolRenderer from "./MultiToolRenderer";
import { RendererComponent } from "./renderMessageComponent";

export function AIMessage({
  rawPackets,
  chatState,
  nodeId,
  otherMessagesCanSwitchTo,
  onMessageSelection,
}: {
  rawPackets: Packet[];
  chatState: FullChatState;
  nodeId: number;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;
}) {
  const markdownRef = useRef<HTMLDivElement>(null);
  const [isRegenerateDropdownVisible, setIsRegenerateDropdownVisible] =
    useState(false);

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
      if (packet.obj.type === PacketType.SEARCH_TOOL_DELTA) {
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
  const uniqueSourceCount = useMemo(() => {
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
                  {chatState.handleFeedback &&
                    stopPacketSeen &&
                    displayComplete && (
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

                            <CustomTooltip showTick line content="Copy">
                              <CopyButton
                                copyAllFn={() =>
                                  copyAll(
                                    getTextContent(rawPackets),
                                    markdownRef
                                  )
                                }
                              />
                            </CustomTooltip>

                            <CustomTooltip
                              showTick
                              line
                              content="Good response"
                            >
                              <HoverableIcon
                                icon={<LikeFeedback size={16} />}
                                onClick={() => chatState.handleFeedback("like")}
                              />
                            </CustomTooltip>

                            <CustomTooltip showTick line content="Bad response">
                              <HoverableIcon
                                icon={<DislikeFeedback size={16} />}
                                onClick={() =>
                                  chatState.handleFeedback("dislike")
                                }
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

                            {nodeId &&
                              (citations.length > 0 ||
                                documentMap.size > 0) && (
                                <>
                                  {chatState.regenerate && (
                                    <div className="h-4 w-px bg-border mx-2" />
                                  )}
                                  <CustomTooltip
                                    showTick
                                    line
                                    content={`${uniqueSourceCount} Sources`}
                                  >
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
                                          updateCurrentDocumentSidebarVisible(
                                            false
                                          );
                                          updateCurrentSelectedNodeForDocDisplay(
                                            null
                                          );
                                        } else {
                                          updateCurrentSelectedNodeForDocDisplay(
                                            toggledNodeId
                                          );
                                          updateCurrentDocumentSidebarVisible(
                                            true
                                          );
                                        }
                                      }}
                                    />
                                  </CustomTooltip>
                                </>
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
