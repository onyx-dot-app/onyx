import { JSX, Key, useMemo } from "react";
import { useTranslations } from "next-intl";
import {
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
  CodingAgentFinal,
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
import { IoBlockLabel } from "@/app/app/message/messageComponents/IoBlockLabel";

// Timeline copy is looked up in components and threaded into the plain step
// helpers below, which cannot call hooks themselves.
type TimelineTranslate = ReturnType<
  typeof useTranslations<"chat.messages.timeline">
>;

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

// Agent alternates between thinking and bash; build a flat ordered list.
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
      const delta = packet.obj as BashToolDelta;
      const open = findOpenBash();
      if (open) {
        open.stdout += delta.stdout || "";
        open.stderr += delta.stderr || "";
        open.exit_code = delta.exit_code;
        open.timed_out = delta.timed_out;
      }
      continue;
    }

    // Any non-delta packet (thinking, next bash, FINAL, ERROR, …) closes the open bash.
    const open = findOpenBash();
    if (open) open.isComplete = true;

    if (packet.obj.type === PacketType.CODING_AGENT_THINKING_DELTA) {
      const delta = packet.obj as CodingAgentThinkingDelta;
      const last = steps[steps.length - 1];
      if (last && last.kind === "thinking") {
        last.content += delta.content;
      } else {
        steps.push({ kind: "thinking", content: delta.content });
      }
    } else if (packet.obj.type === PacketType.BASH_TOOL_START) {
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
    }
  }

  return steps;
}

interface ThinkingStepProps {
  step: ThinkingStepView;
  isLastStep: boolean;
  isHover: boolean;
}

function ThinkingStep({ step, isLastStep, isHover }: ThinkingStepProps) {
  const t = useTranslations("chat.messages.timeline");

  return (
    <StepContainer
      stepIcon={SvgSparkle}
      header={t("codingAgent.thinking.header")}
      isLastStep={isLastStep}
      isHover={isHover}
      collapsible={true}
      supportsCollapsible={true}
    >
      <div className="pl-(--timeline-common-text-padding)">
        <Text as="p" font="main-ui-muted" color="text-02">
          {step.content}
        </Text>
      </div>
    </StepContainer>
  );
}

function bashStepHeader(call: BashStepView, t: TimelineTranslate): string {
  if (!call.isComplete) return t("codingAgent.bashRunning.header");
  if (call.timed_out) return t("codingAgent.bashTimedOut.header");
  return t("codingAgent.bashExit.header", { exitCode: call.exit_code ?? 0 });
}

function bashStepIcon(call: BashStepView) {
  if (!call.isComplete) return SvgTerminal;
  const failed = call.exit_code !== null && call.exit_code !== 0;
  return failed || call.timed_out ? SvgXCircle : SvgCheckCircle;
}

function BashStepBody({ call }: { call: BashStepView }) {
  const t = useTranslations("chat.messages.timeline");
  const hasStdout = call.stdout.length > 0;
  const hasStderr = call.stderr.length > 0;
  const hasResponse = hasStdout || hasStderr || call.isComplete;

  return (
    <div className="flex flex-col gap-3 pl-(--timeline-common-text-padding)">
      <div>
        <IoBlockLabel label={t("codingAgent.bashRequest.label")} />
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

      {hasResponse && (
        <div className="flex flex-col gap-2">
          <IoBlockLabel label={t("codingAgent.bashResponse.label")} />
          {hasStdout && (
            <ExpandableTextDisplay
              title="stdout"
              content={call.stdout}
              maxLines={3}
            />
          )}
          {hasStderr && (
            <ExpandableTextDisplay
              title="stderr"
              content={call.stderr}
              maxLines={3}
            />
          )}
          {!hasStdout && !hasStderr && call.isComplete && (
            <Text as="p" font="main-ui-muted" color="text-04">
              {t("codingAgent.noOutput.text")}
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
  const t = useTranslations("chat.messages.timeline");

  return (
    <StepContainer
      stepIcon={bashStepIcon(call)}
      header={bashStepHeader(call, t)}
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

function renderAgentStep(
  step: AgentStep,
  key: Key,
  isLastStep: boolean,
  isHover: boolean
): JSX.Element {
  return step.kind === "thinking" ? (
    <ThinkingStep
      key={key}
      step={step}
      isLastStep={isLastStep}
      isHover={isHover}
    />
  ) : (
    <BashCallStep
      key={key}
      call={step}
      isLastStep={isLastStep}
      isHover={isHover}
    />
  );
}

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
  const t = useTranslations("chat.messages.timeline");

  return (
    <StepContainer
      stepIcon={SvgCircle}
      header={t("codingAgent.task.header")}
      collapsible={true}
      isLastStep={isLastStep}
      isFirstStep={true}
      isHover={isHover}
    >
      <div className="pl-(--timeline-common-text-padding)">
        <Text as="p" font="main-ui-muted" color="text-02">
          {taskText}
        </Text>
      </div>
    </StepContainer>
  );
}

interface ResponseStepProps {
  answer: string;
  isLastStep: boolean;
  isHover: boolean;
}

function ResponseStep({ answer, isLastStep, isHover }: ResponseStepProps) {
  const t = useTranslations("chat.messages.timeline");

  return (
    <StepContainer
      stepIcon={SvgCheckCircle}
      header={t("codingAgent.response.header")}
      isLastStep={isLastStep}
      isHover={isHover}
      collapsible={true}
      supportsCollapsible={true}
    >
      <div className="pl-(--timeline-common-text-padding)">
        <Text as="p" font="main-ui-muted" color="text-02">
          {answer}
        </Text>
      </div>
    </StepContainer>
  );
}

export const CodingAgentRenderer: MessageRenderer<CodingAgentPacket, {}> = ({
  packets,
  renderType,
  stopPacketSeen,
  isHover = false,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");
  const startPacket = packets.find(
    (p) => p.obj.type === PacketType.CODING_AGENT_START
  )?.obj as CodingAgentStart | undefined;
  const finalPacket = packets.find(
    (p) => p.obj.type === PacketType.CODING_AGENT_FINAL
  )?.obj as CodingAgentFinal | undefined;
  const hasFinal = finalPacket !== undefined;
  const errored = packets.some((p) => p.obj.type === PacketType.ERROR);

  const steps = useMemo(() => buildAgentSteps(packets), [packets]);

  const isComplete = hasFinal || errored;

  const taskText = startPacket
    ? startPacket.repo
      ? t("codingAgent.taskWithRepo.text", {
          query: startPacket.query,
          repo: startPacket.repo,
        })
      : startPacket.query
    : "";

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

  // Condensed modes show only the latest item; fall back to the task before any step streams.
  const latestStep = steps[steps.length - 1];
  const lastStepIsActive = !stopPacketSeen && !isComplete;

  if (renderType === RenderType.HIGHLIGHT) {
    let header: string | null = null;
    let body: JSX.Element | null = null;

    if (finalPacket) {
      header = t("codingAgent.response.header");
      body = (
        <Text as="p" font="main-ui-muted" color="text-02">
          {finalPacket.answer}
        </Text>
      );
    } else if (latestStep?.kind === "bash") {
      header = bashStepHeader(latestStep, t);
      body = <BashStepBody call={latestStep} />;
    } else if (latestStep?.kind === "thinking") {
      header = t("codingAgent.thinking.header");
      body = (
        <Text as="p" font="main-ui-muted" color="text-02">
          {latestStep.content}
        </Text>
      );
    } else if (taskText) {
      header = t("codingAgent.task.header");
      body = (
        <Text as="p" font="main-ui-muted" color="text-03">
          {taskText}
        </Text>
      );
    }

    if (header === null) return wrap(<></>);
    return wrap(
      <div className="flex flex-col gap-1 pl-(--timeline-common-text-padding)">
        <Text as="p" font="main-ui-muted" color="text-04">
          {header}
        </Text>
        {body}
      </div>
    );
  }

  if (renderType === RenderType.COMPACT) {
    if (finalPacket) {
      return wrap(
        <ResponseStep
          answer={finalPacket.answer}
          isLastStep={true}
          isHover={isHover}
        />
      );
    }
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
          isLastStep={lastStepIsActive && steps.length === 0 && !finalPacket}
          isHover={isHover}
        />
      )}
      {steps.map((step, idx) =>
        renderAgentStep(
          step,
          idx,
          lastStepIsActive && idx === steps.length - 1 && !finalPacket,
          isHover
        )
      )}
      {finalPacket && (
        <ResponseStep
          answer={finalPacket.answer}
          isLastStep={true}
          isHover={isHover}
        />
      )}
    </div>
  );
};
