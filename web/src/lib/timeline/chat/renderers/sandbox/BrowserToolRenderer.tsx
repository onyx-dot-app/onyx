import { type ComponentProps, useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgGlobe } from "@opal/icons";
import { richNodes } from "@opal/utils";
import {
  type CustomToolPacket,
  type Packet,
  PacketType,
  readCustomToolCall,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import {
  SandboxCallContent,
  SandboxCallError,
} from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";

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
  const { toolName, call, error } = useMemo(() => {
    let toolName = "";
    let error: string | null = null;
    for (const { obj } of packets) {
      if (obj.type === PacketType.CUSTOM_TOOL_START) {
        toolName = obj.tool_name;
      } else if (obj.type === PacketType.CUSTOM_TOOL_DELTA && obj.error) {
        error = obj.error.message;
      }
    }
    return { toolName, call: readCustomToolCall(packets), error };
  }, [packets]);

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

  const content =
    url || error ? (
      <SandboxCallContent renderType={renderType}>
        <Section alignItems="stretch" gap={1} height="fit">
          {url && (
            <Text as="p" font="secondary-mono" color="text-03">
              {richNodes(<span dir="ltr">{url}</span>)}
            </Text>
          )}
          {error && <SandboxCallError error={error} />}
        </Section>
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
