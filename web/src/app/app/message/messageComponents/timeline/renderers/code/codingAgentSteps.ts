import { nativeContent } from "@/app/app/services/pydanticEvents";
import {
  CodingAgentPacket,
  PacketType,
} from "@/app/app/services/streamingModels";

// Agent alternates between thinking and bash; build a flat ordered list.
export interface ThinkingStepView {
  kind: "thinking";
  content: string;
}

export interface BashStepView {
  kind: "bash";
  cmd: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  isComplete: boolean;
}

export type AgentStep = ThinkingStepView | BashStepView;

export function buildAgentSteps(packets: CodingAgentPacket[]): AgentStep[] {
  const steps: AgentStep[] = [];
  const findOpenBash = (): BashStepView | undefined => {
    for (let i = steps.length - 1; i >= 0; i--) {
      const c = steps[i];
      if (c?.kind === "bash" && !c.isComplete) return c;
    }
    return undefined;
  };

  for (const packet of packets) {
    if (packet.obj.type === PacketType.BASH_TOOL_DELTA) {
      // Fold output; finalization waits for the next non-delta packet.
      const delta = packet.obj;
      const open = findOpenBash();
      if (open) {
        open.stdout += delta.stdout || "";
        open.stderr += delta.stderr || "";
        open.exit_code = delta.exit_code;
        open.timed_out = delta.timed_out;
      }
      continue;
    }

    const nativeText =
      nativeContent(packet, "thinking") +
      (packet.obj.type === PacketType.PYDANTIC_AI &&
      packet.obj.phase !== "report"
        ? nativeContent(packet, "text")
        : "");
    if (packet.obj.type === PacketType.PYDANTIC_AI && !nativeText) continue;

    // Content or a new tool closes the previous command.
    const open = findOpenBash();
    if (open) open.isComplete = true;

    if (
      packet.obj.type === PacketType.CODING_AGENT_THINKING_DELTA ||
      nativeText
    ) {
      const content =
        packet.obj.type === PacketType.CODING_AGENT_THINKING_DELTA
          ? packet.obj.content
          : nativeText;
      const last = steps[steps.length - 1];
      if (last && last.kind === "thinking") {
        last.content += content;
      } else {
        steps.push({ kind: "thinking", content });
      }
    } else if (packet.obj.type === PacketType.BASH_TOOL_START) {
      const start = packet.obj;
      steps.push({
        kind: "bash",
        cmd: start.cmd,
        stdout: "",
        stderr: "",
        exit_code: null,
        timed_out: false,
        isComplete: false,
      });
    }
  }

  return steps;
}
