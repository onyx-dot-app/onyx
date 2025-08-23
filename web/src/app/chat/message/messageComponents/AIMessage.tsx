import {
  Packet,
  PacketType,
  CitationDelta,
  SearchToolDelta,
  ImageGenerationToolDelta,
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
  useSelectedMessageForDocDisplay,
} from "../../stores/useChatSessionStore";
import { copyAll, handleCopy } from "../copyingUtils";
import RegenerateOption from "../../components/RegenerateOption";
import { MessageSwitcher } from "../MessageSwitcher";
import { BlinkingDot } from "../BlinkingDot";
import {
  getTextContent,
  isFinalAnswerComing,
  isStreamingComplete,
  isToolPacket,
} from "../../services/packetUtils";
import { useMessageSwitching } from "./hooks/useMessageSwitching";
import MultiToolRenderer, { RendererComponent } from "./MultiToolRenderer";

export function AIMessage({
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
    isFinalAnswerComing(rawPackets) || isStreamingComplete(rawPackets)
  );

  const [displayComplete, setDisplayComplete] = useState(
    isStreamingComplete(rawPackets)
  );

  // Incremental packet processing state
  const lastProcessedIndexRef = useRef<number>(0);
  const citationsRef = useRef<StreamingCitation[]>([]);
  const seenCitationDocIdsRef = useRef<Set<string>>(new Set());
  const documentMapRef = useRef<Map<string, OnyxDocument>>(new Map());
  const groupedPacketsMapRef = useRef<Map<number, Packet[]>>(new Map());
  const groupedPacketsRef = useRef<{ ind: number; packets: Packet[] }[]>([]);
  const finalAnswerComingRef = useRef<boolean>(isFinalAnswerComing(rawPackets));

  // Reset incremental state when switching messages or when stream resets
  useEffect(() => {
    lastProcessedIndexRef.current = 0;
    citationsRef.current = [];
    seenCitationDocIdsRef.current = new Set();
    documentMapRef.current = new Map();
    groupedPacketsMapRef.current = new Map();
    groupedPacketsRef.current = [];
    finalAnswerComingRef.current = isFinalAnswerComing(rawPackets);
  }, [messageId]);

  // If the upstream replaces packets with a shorter list (reset), clear state
  if (lastProcessedIndexRef.current > rawPackets.length) {
    lastProcessedIndexRef.current = 0;
    citationsRef.current = [];
    seenCitationDocIdsRef.current = new Set();
    documentMapRef.current = new Map();
    groupedPacketsMapRef.current = new Map();
    groupedPacketsRef.current = [];
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
  const selectedMessageForDocDisplay = useSelectedMessageForDocDisplay();
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const updateCurrentSelectedMessageForDocDisplay = useChatSessionStore(
    (state) => state.updateCurrentSelectedMessageForDocDisplay
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
    messageId,
    otherMessagesCanSwitchTo,
    onMessageSelection,
  });

  const groupedPackets = groupedPacketsRef.current;

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
                      className="overflow-x-visible max-w-content-max focus:outline-none select-text"
                      onCopy={(e) => handleCopy(e, markdownRef)}
                    >
                      {groupedPackets.length === 0 ? (
                        // Show blinking dot when no content yet but message is generating
                        <BlinkingDot />
                      ) : (
                        (() => {
                          // Simple split: tools vs non-tools
                          const toolGroups = groupedPackets.filter(
                            (group) =>
                              group.packets[0] && isToolPacket(group.packets[0])
                          ) as { ind: number; packets: Packet[] }[];

                          // Non-tools include messages AND image generation
                          const nonToolGroups =
                            allToolsFullyDisplayed || toolGroups.length === 0
                              ? groupedPackets.filter(
                                  (group) =>
                                    group.packets[0] &&
                                    !isToolPacket(group.packets[0])
                                )
                              : [];

                          return (
                            <>
                              {/* Render tool groups in multi-tool renderer */}
                              {toolGroups.length > 0 && (
                                <MultiToolRenderer
                                  packetGroups={toolGroups}
                                  chatState={chatState}
                                  isComplete={allToolsFullyDisplayed}
                                  isFinalAnswerComing={
                                    finalAnswerComingRef.current
                                  }
                                  onAllToolsDisplayed={() =>
                                    setAllToolsFullyDisplayed(true)
                                  }
                                />
                              )}

                              {/* Render non-tool groups (messages + image generation) in main area */}
                              {nonToolGroups.map((group) => (
                                <RendererComponent
                                  key={group.ind}
                                  packets={group.packets}
                                  chatState={chatState}
                                  onComplete={() => {
                                    // Check if this was the last group
                                    const isLastGroup =
                                      group ===
                                      nonToolGroups[nonToolGroups.length - 1];
                                    if (isLastGroup) {
                                      setDisplayComplete(true);
                                    }
                                  }}
                                  animate={false}
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

                          {messageId &&
                            (citations.length > 0 || documentMap.size > 0) && (
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
                                    messageId={messageId}
                                    onToggle={(messageId) => {
                                      // Toggle sidebar if clicking on the same message
                                      if (
                                        selectedMessageForDocDisplay ===
                                          messageId &&
                                        documentSidebarVisible
                                      ) {
                                        updateCurrentDocumentSidebarVisible(
                                          false
                                        );
                                        updateCurrentSelectedMessageForDocDisplay(
                                          null
                                        );
                                      } else {
                                        updateCurrentSelectedMessageForDocDisplay(
                                          messageId
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
