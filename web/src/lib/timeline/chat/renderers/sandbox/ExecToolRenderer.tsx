import { type ComponentProps, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { Text } from "@opal/components";
import { SvgTerminal } from "@opal/icons";
import {
  ExecCommandStart,
  ExecEnd,
  ExecToolPacket,
  PacketType,
  WriteStdinStart,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/app/app/message/messageComponents/types";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import { HighlightedBashCode } from "@/lib/timeline/chat/renderers/code/HighlightedBashCode";
import {
  SandboxCallContent,
  SandboxCallError,
} from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";
import { useSandboxCallStatus } from "@/lib/sandbox/hooks";

// Escapes for whitespace and DEL; other control characters show in caret
// notation, so "\u0003" (Ctrl-C) reads as ^C.
const ESCAPED_CONTROL_CHARS = new Map([
  ["\n", "\\n"],
  ["\r", "\\r"],
  ["\t", "\\t"],
  ["\u007f", "^?"],
]);

type ExecToolRendererProps = ComponentProps<
  MessageRenderer<ExecToolPacket, {}>
>;

/** One exec_command or write_stdin call: what it ran or sent, its output, and how it ended. */
export function ExecToolRenderer({
  packets,
  onComplete,
  renderType,
  stopPacketSeen,
  children,
}: ExecToolRendererProps) {
  const t = useTranslations("chat.messages.timeline");
  const { start, liveOutput, end } = useMemo(() => {
    let start: ExecCommandStart | WriteStdinStart | null = null;
    // Live output deltas: a preview until exec_end's output replaces it
    let liveOutput = "";
    let end: ExecEnd | null = null;
    for (const { obj } of packets) {
      if (
        obj.type === PacketType.EXEC_COMMAND_START ||
        obj.type === PacketType.WRITE_STDIN_START
      ) {
        start = obj;
      } else if (obj.type === PacketType.EXEC_OUTPUT_DELTA) {
        liveOutput += obj.text;
      } else if (obj.type === PacketType.EXEC_END) {
        end = obj;
      }
    }
    return { start, liveOutput, end };
  }, [packets]);
  const { isComplete, error, stopped } = useSandboxCallStatus(
    packets,
    end,
    stopPacketSeen,
    onComplete
  );
  const output = end === null ? liveOutput : (end.output ?? "");

  if (start === null) {
    return children([{ icon: null, status: null, content: <></> }]);
  }

  const phase = !isComplete
    ? "running"
    : error !== null
      ? "failed"
      : end?.completion === "canceled"
        ? "canceled"
        : "done";
  const status = stopped
    ? t("sandbox.stopped.status")
    : start.type === PacketType.EXEC_COMMAND_START
      ? t("sandbox.exec.status", {
          // A command still running at its exec_end has only started
          phase: phase === "done" && end?.session_id ? "started" : phase,
        })
      : t("sandbox.stdin.status", {
          kind: start.chars ? "send" : "check",
          phase,
          sessionId: start.session_id,
        });

  const content = (
    <SandboxCallContent renderType={renderType}>
      {start.type === PacketType.EXEC_COMMAND_START ? (
        <Section gap={1} alignItems="stretch" height="fit">
          <div className="prose max-w-full">
            <CodeBlock
              className="font-secondary-mono"
              codeText={start.cmd}
              noPadding
            >
              <span className="select-none text-text-03">{"$ "}</span>
              <HighlightedBashCode code={start.cmd} />
            </CodeBlock>
          </div>
          {start.workdir && (
            <Text font="secondary-body" color="text-03">
              {t("sandbox.exec.workdir.label", { workdir: start.workdir })}
            </Text>
          )}
        </Section>
      ) : (
        start.chars && (
          <div className="prose max-w-full">
            <CodeBlock
              className="font-secondary-mono"
              codeText={start.chars}
              noPadding
            >
              {Array.from(
                start.chars,
                (char) =>
                  ESCAPED_CONTROL_CHARS.get(char) ??
                  (char.charCodeAt(0) < 0x20
                    ? `^${String.fromCharCode(char.charCodeAt(0) + 0x40)}`
                    : char)
              ).join("")}
            </CodeBlock>
          </div>
        )
      )}

      {output && (
        <ExpandableTextDisplay
          title={t("sandbox.output.title")}
          content={output}
          maxLines={6}
          isStreaming={!isComplete}
          monospace
        />
      )}

      {end !== null && end.exit_code !== null && (
        <Text
          font="secondary-body"
          color={end.exit_code === 0 ? "text-03" : "status-error-05"}
        >
          {t("sandbox.exitCode.label", { exitCode: end.exit_code })}
        </Text>
      )}
      {end?.completion && end.completion !== "exited" && (
        <Text font="secondary-body" color="status-warning-05">
          {t("sandbox.completion.label", { completion: end.completion })}
        </Text>
      )}
      {end?.session_id && (
        <Text font="secondary-body" color="text-03">
          {t("sandbox.stillRunning.label", { sessionId: end.session_id })}
        </Text>
      )}
      {end?.truncated && (
        <Text font="secondary-body" color="text-03">
          {t("sandbox.truncated.label")}
        </Text>
      )}
      {error !== null && <SandboxCallError error={error} />}
      {end !== null && !output && error === null && !end.session_id && (
        <Text font="secondary-body" color="text-04">
          {t("sandbox.noOutput.text")}
        </Text>
      )}
    </SandboxCallContent>
  );

  return children([
    {
      icon: SvgTerminal,
      status,
      supportsCollapsible: true,
      noPaddingRight: true,
      content,
    },
  ]);
}
