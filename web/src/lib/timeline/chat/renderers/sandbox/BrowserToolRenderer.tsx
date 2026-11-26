import { type ComponentProps, useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { CodePanel } from "@opal/components";
import type { JsonValue } from "@/lib/json";
import {
  SvgBrowserFile,
  SvgEarth,
  SvgKeyboard,
  SvgMousePointer,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  type CustomToolPacket,
  type Packet,
  PacketType,
  readCustomToolCall,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { faviconIcon } from "@/lib/timeline/components/bodies/favicon";
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

const MAX_TYPED_CHARS = 40;

function argString(
  args: Record<string, unknown> | null,
  name: string
): string | null {
  const value = args?.[name];
  return typeof value === "string" && value !== "" ? value : null;
}

/** A `browser_act` call says which action it took, with its text or key. */
function actStatus(
  t: ReturnType<
    typeof useTranslations<"chat.messages.timeline.sandbox.browser">
  >,
  phase: Phase,
  args: Record<string, unknown> | null
): string {
  const text = argString(args, "text");
  const key = argString(args, "key");
  switch (argString(args, "action")) {
    case "click":
      return t("act.click.status", { phase });
    case "type":
      return text
        ? t("act.type.status", {
            phase,
            text:
              text.length > MAX_TYPED_CHARS
                ? `${text.slice(0, MAX_TYPED_CHARS)}…`
                : text,
          })
        : t("act.status", { phase });
    case "hover":
      return t("act.hover.status", { phase });
    case "select":
      return t("act.select.status", { phase });
    case "drag":
      return t("act.drag.status", { phase });
    case "press":
      return key
        ? t("act.press.status", { phase, key })
        : t("act.status", { phase });
    case "scroll":
      return t("act.scroll.status", { phase });
    case "upload":
      return t("act.upload.status", { phase });
    default:
      return t("act.status", { phase });
  }
}

/** Pointer actions get a cursor, typing a keyboard, uploads a browser with a file. */
function actIcon(args: Record<string, unknown> | null): IconFunctionComponent {
  switch (argString(args, "action")) {
    case "click":
    case "hover":
    case "select":
    case "drag":
    case "press":
    case "scroll":
      return SvgMousePointer;
    case "type":
      return SvgKeyboard;
    case "upload":
      return SvgBrowserFile;
    default:
      return SvgEarth;
  }
}

type BrowserToolRendererProps = ComponentProps<
  MessageRenderer<CustomToolPacket, {}>
>;

/** One browser tool call: what it did to the page, by the earth. */
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
      status = actStatus(t, phase, call.args);
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
      icon:
        toolName === "browser_act"
          ? actIcon(call.args)
          : url &&
              (toolName === "browser_open" || toolName === "browser_navigate")
            ? faviconIcon(url, SvgEarth)
            : SvgEarth,
      status,
      supportsCollapsible: true,
      content,
    },
  ]);
}
