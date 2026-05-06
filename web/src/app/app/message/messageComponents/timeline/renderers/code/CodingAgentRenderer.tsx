import { useMemo } from "react";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgCircle,
  SvgSparkle,
  SvgTerminal,
  SvgXCircle,
} from "@opal/icons";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import {
  BashToolDelta,
  BashToolStart,
  CodingAgentPacket,
  CodingAgentStart,
  CodingAgentThinkingDelta,
  PacketType,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/app/app/message/messageComponents/interfaces";
import { StepContainer } from "@/app/app/message/messageComponents/timeline/StepContainer";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import Text from "@/refresh-components/texts/Text";

// Lazy registration for bash highlighting
function ensureBashHljsRegistered() {
  if (!hljs.listLanguages().includes("bash")) {
    hljs.registerLanguage("bash", bash);
  }
}

function HighlightedBashCode({ code }: { code: string }) {
  const highlightedHtml = useMemo(() => {
    ensureBashHljsRegistered();
    try {
      return hljs.highlight(code, { language: "bash" }).value;
    } catch {
      return code
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }
  }, [code]);

  return (
    <span
      dangerouslySetInnerHTML={{ __html: highlightedHtml }}
      className="hljs"
    />
  );
}

// Mirrors the small "Request" / "Response" label CustomToolRenderer uses
// (CustomToolRenderer.tsx:175-180, :233-239) — the same arrow-exchange icon +
// secondary-body label combo.
function IoBlockLabel({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-1">
      <SvgArrowExchange className="w-3 h-3 text-text-02" />
      <Text text04 secondaryBody>
        {label}
      </Text>
    </div>
  );
}

// ── Interleaved step model ────────────────────────────────────────────────
// The agent alternates between thinking and bash calls. We build a flat list
// of steps in packet order so the timeline reflects the real sequence.

interface ThinkingStepView {
  kind: "thinking";
  content: string;
}

interface BashStepView {
  kind: "bash";
  cmd: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  isComplete: boolean;
}

type AgentStep = ThinkingStepView | BashStepView;

function buildAgentSteps(packets: CodingAgentPacket[]): AgentStep[] {
  const steps: AgentStep[] = [];
  for (const packet of packets) {
    if (packet.obj.type === PacketType.CODING_AGENT_THINKING_DELTA) {
      const delta = packet.obj as CodingAgentThinkingDelta;
      const last = steps[steps.length - 1];
      if (last && last.kind === "thinking") {
        last.content += delta.content;
      } else {
        steps.push({ kind: "thinking", content: delta.content });
      }
      continue;
    }
    if (packet.obj.type === PacketType.BASH_TOOL_START) {
      const start = packet.obj as BashToolStart;
      steps.push({
        kind: "bash",
        cmd: start.cmd,
        stdout: "",
        stderr: "",
        exit_code: null,
        timed_out: false,
        isComplete: false,
      });
      continue;
    }
    if (packet.obj.type === PacketType.BASH_TOOL_DELTA) {
      const delta = packet.obj as BashToolDelta;
      // Find the last incomplete bash step to attach the result to
      for (let i = steps.length - 1; i >= 0; i--) {
        const candidate = steps[i];
        if (
          candidate !== undefined &&
          candidate.kind === "bash" &&
          !candidate.isComplete
        ) {
          candidate.stdout += delta.stdout || "";
          candidate.stderr += delta.stderr || "";
          candidate.exit_code = delta.exit_code;
          candidate.timed_out = delta.timed_out;
          candidate.isComplete = true;
          break;
        }
      }
    }
  }
  return steps;
}

// ── Step renderers ────────────────────────────────────────────────────────

interface ThinkingStepProps {
  step: ThinkingStepView;
  isLastStep: boolean;
  isHover: boolean;
}

function ThinkingStep({ step, isLastStep, isHover }: ThinkingStepProps) {
  return (
    <StepContainer
      stepIcon={SvgSparkle}
      header="Thinking"
      isLastStep={isLastStep}
      isHover={isHover}
      collapsible={true}
      supportsCollapsible={true}
    >
      <div className="pl-[var(--timeline-common-text-padding)]">
        <Text as="p" text02 mainUiMuted>
          {step.content}
        </Text>
      </div>
    </StepContainer>
  );
}

interface BashCallStepProps {
  call: BashStepView;
  isLastStep: boolean;
  isHover: boolean;
}

function BashCallStep({ call, isLastStep, isHover }: BashCallStepProps) {
  const failed = call.exit_code !== null && call.exit_code !== 0;
  const stepIcon = !call.isComplete
    ? SvgTerminal
    : failed || call.timed_out
      ? SvgXCircle
      : SvgCheckCircle;
  const hasStdout = call.stdout.length > 0;
  const hasStderr = call.stderr.length > 0;
  const hasResponse = hasStdout || hasStderr || call.isComplete;
  const isStreaming = !call.isComplete;

  const headerText = !call.isComplete
    ? "Bash · running…"
    : call.timed_out
      ? "Bash · timed out"
      : `Bash · exit ${call.exit_code ?? 0}`;

  return (
    <StepContainer
      stepIcon={stepIcon}
      header={headerText}
      isLastStep={isLastStep}
      isHover={isHover}
      collapsible={true}
      supportsCollapsible={true}
      noPaddingRight={true}
    >
      <div className="flex flex-col gap-3 pl-[var(--timeline-common-text-padding)]">
        {/* Request: bash command */}
        <div>
          <IoBlockLabel label="Request" />
          <div className="prose max-w-full">
            <CodeBlock
              className="font-secondary-mono"
              codeText={call.cmd}
              noPadding
            >
              <HighlightedBashCode code={call.cmd} />
            </CodeBlock>
          </div>
        </div>

        {/* Response: stdout / stderr, capped to 3 lines and expandable */}
        {hasResponse && (
          <div className="flex flex-col gap-2">
            <IoBlockLabel label="Response" />
            {hasStdout && (
              <ExpandableTextDisplay
                title="stdout"
                content={call.stdout}
                maxLines={3}
                isStreaming={isStreaming}
              />
            )}
            {hasStderr && (
              <ExpandableTextDisplay
                title="stderr"
                content={call.stderr}
                maxLines={3}
                isStreaming={isStreaming}
              />
            )}
            {!hasStdout && !hasStderr && call.isComplete && (
              <Text as="p" text04 mainUiMuted>
                No output
              </Text>
            )}
          </div>
        )}
      </div>
    </StepContainer>
  );
}

// ── Main renderer ─────────────────────────────────────────────────────────

export const CodingAgentRenderer: MessageRenderer<CodingAgentPacket, {}> = ({
  packets,
  stopPacketSeen,
  isHover = false,
  children,
}) => {
  const startPacket = packets.find(
    (p) => p.obj.type === PacketType.CODING_AGENT_START
  )?.obj as CodingAgentStart | undefined;
  const hasFinal = packets.some(
    (p) => p.obj.type === PacketType.CODING_AGENT_FINAL
  );
  const errored = packets.some((p) => p.obj.type === PacketType.ERROR);

  const steps = useMemo(() => buildAgentSteps(packets), [packets]);

  const isComplete = hasFinal || errored;

  const taskText = startPacket
    ? startPacket.repo
      ? `${startPacket.query}\n\nRepository: ${startPacket.repo}`
      : startPacket.query
    : "";

  return children([
    {
      icon: null,
      status: null,
      content: (
        <div className="flex flex-col">
          {startPacket && (
            <StepContainer
              stepIcon={SvgCircle}
              header="Coding Task"
              collapsible={true}
              isLastStep={!stopPacketSeen && steps.length === 0 && !isComplete}
              isFirstStep={true}
              isHover={isHover}
            >
              <div className="pl-[var(--timeline-common-text-padding)]">
                <Text as="p" text02 mainUiMuted>
                  {taskText}
                </Text>
              </div>
            </StepContainer>
          )}

          {steps.map((step, idx) => {
            const isLastStep =
              !stopPacketSeen && idx === steps.length - 1 && !isComplete;
            if (step.kind === "thinking") {
              return (
                <ThinkingStep
                  key={idx}
                  step={step}
                  isLastStep={isLastStep}
                  isHover={isHover}
                />
              );
            }
            return (
              <BashCallStep
                key={idx}
                call={step}
                isLastStep={isLastStep}
                isHover={isHover}
              />
            );
          })}
        </div>
      ),
      supportsCollapsible: true,
      timelineLayout: "content",
    },
  ]);
};
