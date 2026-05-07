import { JSX, Key, useMemo } from "react";
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
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { StepContainer } from "@/app/app/message/messageComponents/timeline/StepContainer";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import { Text } from "@opal/components";

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
      <Text font="secondary-body" color="text-04">
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
        <Text as="p" font="main-ui-muted" color="text-02">
          {step.content}
        </Text>
      </div>
    </StepContainer>
  );
}

function bashStepHeader(call: BashStepView): string {
  if (!call.isComplete) return "Bash · running…";
  if (call.timed_out) return "Bash · timed out";
  return `Bash · exit ${call.exit_code ?? 0}`;
}

function bashStepIcon(call: BashStepView) {
  if (!call.isComplete) return SvgTerminal;
  const failed = call.exit_code !== null && call.exit_code !== 0;
  return failed || call.timed_out ? SvgXCircle : SvgCheckCircle;
}

function BashStepBody({ call }: { call: BashStepView }) {
  const hasStdout = call.stdout.length > 0;
  const hasStderr = call.stderr.length > 0;
  const hasResponse = hasStdout || hasStderr || call.isComplete;
  const isStreaming = !call.isComplete;

  return (
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
            <Text as="p" font="main-ui-muted" color="text-04">
              No output
            </Text>
          )}
        </div>
      )}
    </div>
  );
}

interface BashCallStepProps {
  call: BashStepView;
  isLastStep: boolean;
  isHover: boolean;
}

function BashCallStep({ call, isLastStep, isHover }: BashCallStepProps) {
  return (
    <StepContainer
      stepIcon={bashStepIcon(call)}
      header={bashStepHeader(call)}
      isLastStep={isLastStep}
      isHover={isHover}
      collapsible={true}
      supportsCollapsible={true}
      noPaddingRight={true}
    >
      <BashStepBody call={call} />
    </StepContainer>
  );
}

// Dispatches a step to its renderer (shared by COMPACT and FULL paths).
function renderAgentStep(
  step: AgentStep,
  key: Key,
  isLastStep: boolean,
  isHover: boolean
): JSX.Element {
  if (step.kind === "thinking") {
    return (
      <ThinkingStep
        key={key}
        step={step}
        isLastStep={isLastStep}
        isHover={isHover}
      />
    );
  }
  return (
    <BashCallStep
      key={key}
      call={step}
      isLastStep={isLastStep}
      isHover={isHover}
    />
  );
}

// "Coding Task" step container — shared by COMPACT-fallback and FULL paths.
interface CodingTaskStepProps {
  taskText: string;
  isLastStep: boolean;
  isHover: boolean;
}

function CodingTaskStep({
  taskText,
  isLastStep,
  isHover,
}: CodingTaskStepProps) {
  return (
    <StepContainer
      stepIcon={SvgCircle}
      header="Coding Task"
      collapsible={true}
      isLastStep={isLastStep}
      isFirstStep={true}
      isHover={isHover}
    >
      <div className="pl-[var(--timeline-common-text-padding)]">
        <Text as="p" font="main-ui-muted" color="text-02">
          {taskText}
        </Text>
      </div>
    </StepContainer>
  );
}

// ── Main renderer ─────────────────────────────────────────────────────────

export const CodingAgentRenderer: MessageRenderer<CodingAgentPacket, {}> = ({
  packets,
  renderType,
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

  // All three render modes return a single result with the same shape; only
  // the inner content changes.
  const wrap = (content: JSX.Element) =>
    children([
      {
        icon: null,
        status: null,
        content,
        supportsCollapsible: true,
        timelineLayout: "content",
      },
    ]);

  // Condensed modes show only the latest active item — falling back to the
  // task when no thinking/bash step has streamed yet.
  const latestStep = steps[steps.length - 1];
  const lastStepIsActive = !stopPacketSeen && !isComplete;

  if (renderType === RenderType.HIGHLIGHT) {
    let header: string | null = null;
    let body: JSX.Element | null = null;

    if (latestStep?.kind === "bash") {
      header = bashStepHeader(latestStep);
      body = <BashStepBody call={latestStep} />;
    } else if (latestStep?.kind === "thinking") {
      header = "Thinking";
      body = (
        <Text as="p" font="main-ui-muted" color="text-02">
          {latestStep.content}
        </Text>
      );
    } else if (taskText) {
      header = "Coding Task";
      body = (
        <Text as="p" font="main-ui-muted" color="text-03">
          {taskText}
        </Text>
      );
    }

    if (header === null) return wrap(<></>);
    return wrap(
      <div className="flex flex-col gap-1 pl-[var(--timeline-common-text-padding)]">
        <Text as="p" font="main-ui-muted" color="text-04">
          {header}
        </Text>
        {body}
      </div>
    );
  }

  if (renderType === RenderType.COMPACT) {
    if (latestStep) {
      return wrap(
        renderAgentStep(latestStep, "latest", lastStepIsActive, isHover)
      );
    }
    if (startPacket) {
      return wrap(
        <CodingTaskStep
          taskText={taskText}
          isLastStep={lastStepIsActive}
          isHover={isHover}
        />
      );
    }
    return wrap(<></>);
  }

  return wrap(
    <div className="flex flex-col">
      {startPacket && (
        <CodingTaskStep
          taskText={taskText}
          isLastStep={lastStepIsActive && steps.length === 0}
          isHover={isHover}
        />
      )}
      {steps.map((step, idx) =>
        renderAgentStep(
          step,
          idx,
          lastStepIsActive && idx === steps.length - 1,
          isHover
        )
      )}
    </div>
  );
};
