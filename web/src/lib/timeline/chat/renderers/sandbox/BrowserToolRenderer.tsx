import { type ComponentProps, useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { CodePanel } from "@opal/components";
import type { JsonValue } from "@/lib/json";
import { SvgGlobe } from "@opal/icons";
import {
  type CustomToolPacket,
  type Packet,
  PacketType,
  readCustomToolCall,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { SandboxCallContent } from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";
import { ToolFields } from "@/lib/timeline/chat/message/messageComponents/renderers/CustomToolRenderer";
import { flatFields, isEmptyPayload } from "@/lib/timeline/chat/toolPayload";

/** The sandbox's browser tools (backend `browser_tools.py:BROWSER_TOOLS`). */
const BROWSER_TOOL_NAMES: ReadonlySet<string> = new Set([
  "browser_status",
  "browser_open",
  "browser_navigate",
  "browser_snapshot",
  "browser_act",
  "browser_wait_for",
  "browser_evaluate",
  "browser_dialog",
]);

export function isBrowserToolPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.CUSTOM_TOOL_START &&
    BROWSER_TOOL_NAMES.has(packet.obj.tool_name)
  );
}

type Phase = "running" | "failed" | "canceled" | "done";

function host(url: string): string {
  try {
    return new URL(url).host || url;
  } catch {
    return url;
  }
}

type BrowserToolRendererProps = ComponentProps<
  MessageRenderer<CustomToolPacket, {}>
>;

/** One browser tool call: what it did to the page, by a globe. */
export function BrowserToolRenderer({
  packets,
  onComplete,
  renderType,
  stopPacketSeen,
  children,
}: BrowserToolRendererProps) {
  const t = useTranslations("chat.messages.timeline.sandbox.browser");
  const tCustom = useTranslations("chat.messages.customTool");
  const { toolName, call, error, data, toolArgs } = useMemo(() => {
    let toolName = "";
    let toolArgs: JsonValue | undefined = undefined;
    let error: string | null = null;
    let data: JsonValue | undefined = undefined;
    for (const { obj } of packets) {
      if (obj.type === PacketType.CUSTOM_TOOL_START) {
        toolName = obj.tool_name;
      } else if (obj.type === PacketType.CUSTOM_TOOL_ARGS) {
        toolArgs = obj.tool_args;
      } else if (obj.type === PacketType.CUSTOM_TOOL_DELTA) {
        data = obj.data;
        if (obj.error) error = obj.error.message;
      }
    }
    return {
      toolName,
      call: readCustomToolCall(packets),
      error,
      data,
      toolArgs,
    };
  }, [packets]);
  const argFields = useMemo(() => flatFields(toolArgs), [toolArgs]);
  const dataFields = useMemo(() => flatFields(data), [data]);

  useEffect(() => {
    if (call.isComplete) onComplete();
  }, [call.isComplete, onComplete]);

  const phase: Phase = call.isComplete
    ? call.failed
      ? "failed"
      : "done"
    : stopPacketSeen
      ? "canceled"
      : "running";
  const url = typeof call.args?.url === "string" ? call.args.url : null;
  const history =
    typeof call.args?.history === "string" ? call.args.history : null;

  let status: string;
  switch (toolName) {
    case "browser_open":
      status = url
        ? t("open.status", { phase, target: host(url) })
        : t("openBlank.status", { phase });
      break;
    case "browser_navigate":
      status = url
        ? t("navigate.status", { phase, target: host(url) })
        : t("history.status", { phase, history: history ?? "reload" });
      break;
    case "browser_snapshot":
      status = t("snapshot.status", { phase });
      break;
    case "browser_act":
      status = t("act.status", { phase });
      break;
    case "browser_wait_for":
      status = t("waitFor.status", { phase });
      break;
    case "browser_evaluate":
      status = t("evaluate.status", { phase });
      break;
    case "browser_dialog":
      status = t("dialog.status", { phase });
      break;
    default:
      status = t("check.status", { phase });
  }

  const showArgs = !isEmptyPayload(toolArgs);
  const showData = !isEmptyPayload(data);
  // The request, then the page's response or the call's error.
  const content =
    showArgs || showData || error ? (
      <SandboxCallContent renderType={renderType}>
        <CodePanel>
          {showArgs && (
            <>
              <CodePanel.Header
                title={tCustom("requestBlock.label")}
                copyText={JSON.stringify(toolArgs, null, 2)}
              />
              {argFields ? (
                <CodePanel.Content>
                  <ToolFields fields={argFields} />
                </CodePanel.Content>
              ) : (
                <CodePanel.Output>
                  {JSON.stringify(toolArgs, null, 2)}
                </CodePanel.Output>
              )}
            </>
          )}
          {(showData || error) && (
            <>
              <CodePanel.Header title={tCustom("responseBlock.label")} />
              {error ? (
                <CodePanel.Output error>{error}</CodePanel.Output>
              ) : dataFields ? (
                <CodePanel.Content>
                  <ToolFields fields={dataFields} />
                </CodePanel.Content>
              ) : (
                <CodePanel.Output>
                  {typeof data === "string" ? data : JSON.stringify(data)}
                </CodePanel.Output>
              )}
            </>
          )}
        </CodePanel>
      </SandboxCallContent>
    ) : null;

  return children([
    {
      icon: SvgGlobe,
      status,
      supportsCollapsible: true,
      content,
    },
  ]);
}
