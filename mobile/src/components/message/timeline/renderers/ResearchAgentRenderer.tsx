// ResearchAgentRenderer.tsx — deep-research sub-agent. Functional port: shows the
// research task and the streamed intermediate report (markdown). The web version
// also recursively renders nested tool calls (by sub_turn_index); that recursion
// is simplified here to the report + task (documented functional-coverage gap).

import { useCallback, useEffect, useMemo, useRef } from "react";
import { View } from "react-native";

import {
  PacketType,
  type ResearchAgentPacket,
  type ResearchAgentStart,
  type IntermediateReportDelta,
} from "@/lib/types";
import type { MessageRendererProps } from "@/components/message/interfaces";
import { Text } from "@/components/opal";
import { Markdown } from "@/components/markdown";
import { ExpandableTextDisplay } from "@/components/message/ExpandableTextDisplay";
import { timelineTokens as T } from "@/theme/timelineTokens";

export function ResearchAgentRenderer({
  packets,
  state,
  onComplete,
  children,
}: MessageRendererProps<ResearchAgentPacket>) {
  const { task, report, hasEnd } = useMemo(() => {
    const startPacket = packets.find(
      (p) => p.obj.type === PacketType.RESEARCH_AGENT_START
    );
    const task =
      startPacket && (startPacket.obj as ResearchAgentStart).research_task
        ? (startPacket.obj as ResearchAgentStart).research_task
        : "";
    const report = packets
      .filter((p) => p.obj.type === PacketType.INTERMEDIATE_REPORT_DELTA)
      .map((p) => (p.obj as IntermediateReportDelta).content)
      .join("");
    // Research agents complete on a PARENT-level section_end (sub_turn_index null).
    const end = packets.some((p) => {
      const t = p.obj.type as PacketType;
      return (
        (t === PacketType.SECTION_END || t === PacketType.ERROR) &&
        (p.placement.sub_turn_index === undefined ||
          p.placement.sub_turn_index === null)
      );
    });
    return { task, report, hasEnd: end };
  }, [packets]);

  const firedRef = useRef(false);
  useEffect(() => {
    if (hasEnd && !firedRef.current) {
      firedRef.current = true;
      onComplete();
    }
  }, [hasEnd, onComplete]);

  const renderMarkdown = useCallback(
    (text: string, isExpanded: boolean) => (
      <Markdown
        variant={isExpanded ? "muted" : "muted-collapsed"}
        citations={state.citations}
        documents={state.docs}
      >
        {text}
      </Markdown>
    ),
    [state.citations, state.docs]
  );

  return children([
    {
      icon: report.length > 0 ? "book-open" : "user",
      status: report.length > 0 ? "Research Report" : "Researching",
      noPaddingRight: true,
      content: (
        <View style={{ paddingLeft: T.timelineCommonTextPadding, gap: 6 }}>
          {task.length > 0 && (
            <Text font="secondary-body" color="text-04">
              {task}
            </Text>
          )}
          {report.length > 0 && (
            <ExpandableTextDisplay
              title="Research Report"
              content={report}
              renderContent={renderMarkdown}
              isStreaming={!hasEnd}
            />
          )}
        </View>
      ),
    },
  ]);
}

export default ResearchAgentRenderer;
