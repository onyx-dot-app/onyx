// DeepResearchPlanRenderer.tsx — streams the deep-research plan markdown.
// Ported (functional) from web DeepResearchPlanRenderer.

import { useCallback, useEffect, useMemo, useRef } from "react";
import { View } from "react-native";

import {
  PacketType,
  type DeepResearchPlanPacket,
  type DeepResearchPlanDelta,
} from "@/lib/types";
import type { MessageRendererProps } from "@/components/message/interfaces";
import { Markdown } from "@/components/markdown";
import { ExpandableTextDisplay } from "@/components/message/ExpandableTextDisplay";
import { timelineTokens as T } from "@/theme/timelineTokens";

export function DeepResearchPlanRenderer({
  packets,
  onComplete,
  children,
}: MessageRendererProps<DeepResearchPlanPacket>) {
  const { content, hasEnd } = useMemo(() => {
    const deltas = packets
      .filter((p) => p.obj.type === PacketType.DEEP_RESEARCH_PLAN_DELTA)
      .map((p) => (p.obj as DeepResearchPlanDelta).content)
      .join("");
    const end = packets.some((p) => {
      const t = p.obj.type as PacketType;
      return t === PacketType.SECTION_END || t === PacketType.ERROR;
    });
    return { content: deltas, hasEnd: end };
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
      <Markdown variant={isExpanded ? "muted" : "muted-collapsed"}>{text}</Markdown>
    ),
    []
  );

  return children([
    {
      icon: "circle",
      status: hasEnd ? "Generated plan" : "Generating plan",
      noPaddingRight: true,
      content: (
        <View style={{ paddingLeft: T.timelineCommonTextPadding }}>
          <ExpandableTextDisplay
            title="Research Plan"
            content={content}
            renderContent={renderMarkdown}
            isStreaming={!hasEnd}
          />
        </View>
      ),
    },
  ]);
}

export default DeepResearchPlanRenderer;
