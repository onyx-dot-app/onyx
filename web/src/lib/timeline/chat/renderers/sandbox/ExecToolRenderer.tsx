import { type ComponentProps, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { CodePanel, Text } from "@opal/components";
import { STEP_ICONS } from "@/lib/timeline/icons";
import {
  ExecCommandStart,
  ExecEnd,
  ExecToolPacket,
  PacketType,
  WriteStdinStart,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { stripAnsi } from "@/lib/sandbox/ansi";
import {
  didExecFail,
  isExpectedInterrupt,
  isInterruptInput,
} from "@/lib/timeline/chat/transformers";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
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
  const output = stripAnsi(end === null ? liveOutput : (end.output ?? ""));

  // A call replayed from history starts at the top of its output.
  const [followOutput] = useState(!isComplete);

  if (start === null) {
    return children([{ icon: null, status: null, content: <></> }]);
  }

  const sentInterrupt =
    start.type === PacketType.WRITE_STDIN_START &&
    isInterruptInput(start.chars);
  const commandFailed = end !== null && didExecFail(end, sentInterrupt);
  const phase = !isComplete
    ? "running"
    : error !== null || commandFailed
      ? "failed"
      : end?.completion === "canceled"
        ? "canceled"
        : "done";
  const showDeadlineInTitle =
    isComplete && !stopped && end?.completion === "deadline_exceeded";
  // Input or a poll that ends the command in failure names how it ended.
  const showPollFailure =
    isComplete &&
    !stopped &&
    commandFailed &&
    error === null &&
    start.type === PacketType.WRITE_STDIN_START;
  const status = stopped
    ? t("sandbox.stopped.status")
    : showDeadlineInTitle || (showPollFailure && end?.completion === "signaled")
      ? t("sandbox.completion.label", {
          completion: end?.completion ?? "exited",
        })
      : showPollFailure && end?.exit_code != null
        ? t("sandbox.exitCode.label", { exitCode: end.exit_code })
        : start.type === PacketType.EXEC_COMMAND_START
          ? t("sandbox.exec.status", {
              // A command still running at its exec_end has only started
              phase: phase === "done" && end?.session_id ? "started" : phase,
            })
          : start.session_id
            ? t("sandbox.stdin.status", {
                kind: start.chars ? "send" : "check",
                phase,
                sessionId: start.session_id,
              })
            : // Interrupted or wrong-typed arguments have no session ID
              t("sandbox.stdin.noSession.status", {
                kind: start.chars ? "send" : "check",
                phase,
              });

  // The output shares the command's panel: it streams into the output band,
  // which waits with a loading shimmer until the first output arrives. A
  // finished command with no output says so, and its exit code closes the
  // panel.
  const panelOutput =
    output ||
    (end !== null && error === null && !end.session_id
      ? t("sandbox.noOutput.text")
      : "");
  const outputLoading = !isComplete && !output;
  const interrupted = isExpectedInterrupt(end, sentInterrupt);
  // Only a failure names its exit code.
  const exitCode =
    end !== null &&
    end.exit_code !== null &&
    end.exit_code !== 0 &&
    !interrupted
      ? t("sandbox.exitCode.label", { exitCode: end.exit_code })
      : undefined;

  const content = (
    <SandboxCallContent renderType={renderType}>
      {start.type === PacketType.EXEC_COMMAND_START ? (
        <CommandBody
          command={start.cmd}
          language="bash"
          prompt="$ "
          // Where it ran, when the call names a directory.
          comment={
            start.workdir
              ? t("sandbox.exec.workdir.label", { workdir: start.workdir })
              : undefined
          }
          output={panelOutput}
          outputLoading={outputLoading}
          outputFollow={followOutput}
          emptyLabel=""
          footer={exitCode}
        />
      ) : (
        <CodePanel>
          {start.chars && (
            <CodePanel.Lines
              copyText={start.chars}
              lines={[
                {
                  content: Array.from(
                    start.chars,
                    (char) =>
                      ESCAPED_CONTROL_CHARS.get(char) ??
                      (char.charCodeAt(0) < 0x20
                        ? `^${String.fromCharCode(char.charCodeAt(0) + 0x40)}`
                        : char)
                  ).join(""),
                },
              ]}
            />
          )}
          {panelOutput ? (
            <CodePanel.Output follow={followOutput}>
              {panelOutput}
            </CodePanel.Output>
          ) : (
            outputLoading && <CodePanel.Output loading />
          )}
          {exitCode && <CodePanel.Footer title={exitCode} />}
        </CodePanel>
      )}

      {end?.completion &&
        end.completion !== "exited" &&
        !showDeadlineInTitle &&
        !(showPollFailure && end.completion === "signaled") && (
          // A kill or a time limit fails the step, so it reads as an error.
          <Text
            font="secondary-body"
            color={
              end.completion === "canceled" || interrupted
                ? "status-warning-05"
                : "status-error-05"
            }
          >
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
    </SandboxCallContent>
  );

  return children([
    {
      icon: STEP_ICONS.execute,
      status,
      supportsCollapsible: true,
      // A command shows at once; input to a session waits for its characters,
      // its output or its end.
      content:
        start.type === PacketType.EXEC_COMMAND_START ||
        start.chars ||
        output ||
        end !== null ||
        error !== null
          ? content
          : null,
    },
  ]);
}
