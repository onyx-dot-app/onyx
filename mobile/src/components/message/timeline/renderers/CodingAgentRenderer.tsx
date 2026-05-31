// CodingAgentRenderer.tsx — coding agent. Functional port: shows the agent's
// thinking, each bash command + output, and the final response in one
// collapsible step. The web version renders each sub-step as its own
// StepContainer; collapsed here into a single step (documented simplification).

import { useEffect, useMemo, useRef } from "react";
import { View } from "react-native";

import {
  PacketType,
  type CodingAgentPacket,
  type CodingAgentThinkingDelta,
  type CodingAgentFinal,
  type BashToolStart,
  type BashToolDelta,
} from "@/lib/types";
import type { MessageRendererProps } from "@/components/message/interfaces";
import { Text } from "@/components/opal";
import { Markdown } from "@/components/markdown";
import { CodeBlock } from "@/components/markdown/CodeBlock";
import { timelineTokens as T } from "@/theme/timelineTokens";

interface BashView {
  cmd: string;
  stdout: string;
  stderr: string;
}

export function CodingAgentRenderer({
  packets,
  onComplete,
  children,
}: MessageRendererProps<CodingAgentPacket>) {
  const { thinking, bashes, answer, isComplete } = useMemo(() => {
    let thinking = "";
    const bashes: BashView[] = [];
    let answer = "";
    let current: BashView | null = null;

    for (const p of packets) {
      switch (p.obj.type) {
        case PacketType.CODING_AGENT_THINKING_DELTA:
          thinking += (p.obj as CodingAgentThinkingDelta).content;
          break;
        case PacketType.BASH_TOOL_START:
          current = { cmd: (p.obj as BashToolStart).cmd, stdout: "", stderr: "" };
          bashes.push(current);
          break;
        case PacketType.BASH_TOOL_DELTA: {
          const d = p.obj as BashToolDelta;
          if (current) {
            current.stdout += d.stdout ?? "";
            current.stderr += d.stderr ?? "";
          }
          break;
        }
        case PacketType.CODING_AGENT_FINAL:
          answer = (p.obj as CodingAgentFinal).answer;
          break;
      }
    }

    const isComplete = packets.some(
      (p) =>
        p.obj.type === PacketType.CODING_AGENT_FINAL ||
        p.obj.type === PacketType.ERROR
    );
    return { thinking, bashes, answer, isComplete };
  }, [packets]);

  const firedRef = useRef(false);
  useEffect(() => {
    if (isComplete && !firedRef.current) {
      firedRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  return children([
    {
      icon: "terminal",
      status: isComplete ? "Coding agent" : "Coding…",
      noPaddingRight: true,
      content: (
        <View style={{ paddingLeft: T.timelineCommonTextPadding, gap: 8 }}>
          {thinking.length > 0 && <Markdown variant="muted">{thinking}</Markdown>}
          {bashes.map((b, i) => (
            <View key={i} style={{ gap: 4 }}>
              <CodeBlock code={b.cmd} language="bash" />
              {b.stdout.length > 0 && (
                <Text font="secondary-mono" color="text-03">
                  {b.stdout}
                </Text>
              )}
              {b.stderr.length > 0 && (
                <Text font="secondary-mono" color="status-error-05">
                  {b.stderr}
                </Text>
              )}
            </View>
          ))}
          {answer.length > 0 && <Markdown variant="muted">{answer}</Markdown>}
        </View>
      ),
    },
  ]);
}

export default CodingAgentRenderer;
