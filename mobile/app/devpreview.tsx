// DEV-ONLY harness for the AgentMessage timeline + citations via mock packets.
// Reach via mobile://devpreview. Safe to delete; not linked from any screen.

import { ScrollView, View, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Text } from "@/components/opal";
import { SvgLogOut } from "@/components/icons";
import { useToken } from "@/theme/ThemeProvider";
import { AgentMessage } from "@/components/message/AgentMessage";
import { CitationSheetProvider } from "@/components/message/sources/CitationSheet";
import { ExpandedTimelineContent } from "@/components/message/timeline/ExpandedTimelineContent";
import { TimelineRoot } from "@/components/message/timeline/primitives/TimelineRoot";
import { createInitialState, processPackets } from "@/state/timeline/packetProcessor";
import {
  transformPacketGroups,
  groupStepsByTurn,
} from "@/state/timeline/transformers";
import type { FullChatState } from "@/components/message/interfaces";
import {
  PacketType,
  type Packet,
  type OnyxDocument,
  type MinimalAgent,
} from "@/lib/types";

const agent: MinimalAgent = {
  id: 0,
  name: "Onyx",
  description: "Assistant",
} as MinimalAgent;

function doc(id: string, name: string, link: string): OnyxDocument {
  return {
    document_id: id,
    semantic_identifier: name,
    link,
    source_type: "web" as OnyxDocument["source_type"],
    blurb:
      "Onyx connects to your company's docs, apps and people and answers questions with cited sources.",
    boost: 0,
    hidden: false,
    score: 0.9,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: "2026-05-20T10:00:00Z",
    is_internet: true,
  };
}

const D1 = doc("doc-1", "Onyx Overview", "https://onyx.app");
const D2 = doc("doc-2", "Onyx Pricing", "https://onyx.app/pricing");

const completedPackets: Packet[] = [
  { placement: { turn_index: 0 }, obj: { type: PacketType.REASONING_START } },
  {
    placement: { turn_index: 0 },
    obj: {
      type: PacketType.REASONING_DELTA,
      reasoning:
        "# Understanding the question\nThe user wants to know what Onyx is and how it is priced. I should search the internal docs and then summarize with citations.",
    },
  },
  { placement: { turn_index: 0 }, obj: { type: PacketType.REASONING_DONE } },
  {
    placement: { turn_index: 1 },
    obj: { type: PacketType.SEARCH_TOOL_START, is_internet_search: false },
  },
  {
    placement: { turn_index: 1 },
    obj: {
      type: PacketType.SEARCH_TOOL_QUERIES_DELTA,
      queries: ["what is onyx", "onyx pricing"],
    },
  },
  {
    placement: { turn_index: 1 },
    obj: {
      type: PacketType.SEARCH_TOOL_DOCUMENTS_DELTA,
      documents: [D1, D2],
    },
  },
  { placement: { turn_index: 1 }, obj: { type: PacketType.SECTION_END } },
  {
    placement: { turn_index: 2 },
    obj: {
      type: PacketType.MESSAGE_START,
      id: "m1",
      content: "",
      final_documents: [D1, D2],
      pre_answer_processing_seconds: 4,
    },
  },
  {
    placement: { turn_index: 2 },
    obj: { type: PacketType.CITATION_INFO, citation_number: 1, document_id: "doc-1" },
  },
  {
    placement: { turn_index: 2 },
    obj: {
      type: PacketType.MESSAGE_DELTA,
      content:
        "**Onyx** is an open-source Gen-AI and enterprise search platform that connects to your company's documents, apps, and people [[1]](https://onyx.app).\n\nIt offers a free Community Edition and paid Enterprise tiers ",
    },
  },
  {
    placement: { turn_index: 2 },
    obj: { type: PacketType.CITATION_INFO, citation_number: 2, document_id: "doc-2" },
  },
  {
    placement: { turn_index: 2 },
    obj: {
      type: PacketType.MESSAGE_DELTA,
      content:
        "[[2]](https://onyx.app/pricing).\n\n- Connects to many data sources\n- Streams answers with `inline` citations\n- Self-hostable",
    },
  },
  { placement: { turn_index: 2 }, obj: { type: PacketType.SECTION_END } },
  { placement: { turn_index: 0 }, obj: { type: PacketType.STOP } },
];

// Reasoning only, no stop -> live "Thinking" header + collapsed preview.
const streamingPackets: Packet[] = [
  { placement: { turn_index: 0 }, obj: { type: PacketType.REASONING_START } },
  {
    placement: { turn_index: 0 },
    obj: {
      type: PacketType.REASONING_DELTA,
      reasoning:
        "Let me break this problem down step by step. First I need to consider the user's intent and what they are really asking for. Then I should gather the relevant context from the available documents. After that I will weigh the trade-offs between the possible approaches, check for edge cases, and only then compose a clear, well-structured answer with citations. This reasoning intentionally runs well past four lines so the collapsed preview clamp is visible.",
    },
  },
];

const chatState: FullChatState = { agent, docs: [D1, D2] };

const expandedTurnGroups = groupStepsByTurn(
  transformPacketGroups(
    processPackets(
      createInitialState(99),
      completedPackets.filter((p) => p.obj.type !== PacketType.STOP)
    ).toolGroups
  )
);

function LogoutRowPreview() {
  const logoutColor = useToken("text-04");
  return (
    <View>
      <Text font="secondary-body" color="text-03" style={{ marginBottom: 8 }}>
        Sidebar footer: Log out button
      </Text>
      <View className="bg-background-tint-02 rounded-[8px]">
        <View className="border-t border-border-01 px-2 pb-1 pt-2">
          <Pressable className="h-10 flex-row items-center gap-2 rounded-[8px] px-2 active:bg-background-tint-03">
            <SvgLogOut size={18} color={logoutColor} />
            <Text font="main-ui-body" color="text-04">
              Log out
            </Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

export default function DevPreview() {
  return (
    <SafeAreaView style={{ flex: 1 }} className="bg-background-neutral-00">
      <CitationSheetProvider>
        <ScrollView contentContainerStyle={{ padding: 12, gap: 24 }}>
          <Text font="heading-h2" color="text-05">
            AgentMessage preview
          </Text>

          <LogoutRowPreview />

          <View>
            <Text font="secondary-body" color="text-03" style={{ marginBottom: 8 }}>
              Streaming thinking (4-line clamp)
            </Text>
            <AgentMessage
              rawPackets={streamingPackets}
              packetCount={streamingPackets.length}
              nodeId={5}
              chatState={chatState}
            />
          </View>

          <View>
            <Text font="secondary-body" color="text-03" style={{ marginBottom: 8 }}>
              Expanded timeline (rail + reasoning + search chips)
            </Text>
            <TimelineRoot>
              <ExpandedTimelineContent
                turnGroups={expandedTurnGroups}
                chatState={chatState}
                stopPacketSeen
                isSingleStep={false}
                userStopped={false}
                showDoneStep
                showStoppedStep={false}
                hasDoneIndicator
              />
            </TimelineRoot>
          </View>

          <View>
            <Text font="secondary-body" color="text-03" style={{ marginBottom: 8 }}>
              Completed turn (timeline + inline citations)
            </Text>
            <AgentMessage
              rawPackets={completedPackets}
              packetCount={completedPackets.length}
              nodeId={1}
              chatState={chatState}
              processingDurationSeconds={4}
            />
          </View>

          <View>
            <Text font="secondary-body" color="text-03" style={{ marginBottom: 8 }}>
              Streaming turn (thinking block)
            </Text>
            <AgentMessage
              rawPackets={streamingPackets}
              packetCount={streamingPackets.length}
              nodeId={2}
              chatState={chatState}
            />
          </View>
        </ScrollView>
      </CitationSheetProvider>
    </SafeAreaView>
  );
}
