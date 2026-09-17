import { PacketLayout } from "@/app/app/services/packetLayout";
import {
  ChatItem,
  Packet,
  PacketIdentity,
  ResponseItem,
  StopReason,
  ToolItem,
  ToolMetadata,
} from "@/app/app/services/streamingModels";

export function itemKey(item: Pick<ResponseItem, "identity">): string {
  const identity = item.identity;
  return JSON.stringify([
    identity.response_id,
    identity.message_id,
    identity.tool_call_id,
    identity.part_id,
  ]);
}

/** Apply the same complete item shape used by history, or one incremental update. */
export class ResponseItems {
  readonly items = new Map<string, ResponseItem>();
  private readonly layout = new PacketLayout();

  apply(packet: Packet): void {
    const { obj, identity } = packet;
    if (obj.type === "stop") {
      const status =
        obj.stop_reason === StopReason.USER_CANCELLED
          ? "cancelled"
          : "complete";
      for (const [key, item] of this.items) {
        if (identity && item.identity.response_id !== identity.response_id)
          continue;
        if (
          item.content.status !== "running" &&
          item.content.status !== "pending"
        )
          continue;
        this.items.set(key, { ...item, content: { ...item.content, status } });
      }
      return;
    }
    if (!identity) {
      if (obj.type === "item_update" || obj.type === "item_delta") {
        throw new Error("Content update requires an item identity");
      }
      return;
    }
    if (obj.type === "run_update" && obj.status !== "running") {
      for (const [key, item] of this.items) {
        if (
          item.identity.run_id === identity.run_id &&
          (item.content.status === "running" ||
            item.content.status === "pending")
        ) {
          this.items.set(key, {
            ...item,
            content: { ...item.content, status: obj.status },
          });
        }
      }
      return;
    }
    const key = itemKey({ identity });
    if (obj.type === "item_update") {
      const placement = this.layout.place(identity, packet.model_index ?? 0);
      this.items.set(key, { identity, placement, content: obj.item });
      return;
    }
    if (obj.type !== "item_delta") return;
    const existing = this.items.get(key);
    if (!existing) throw new Error(`Delta has no item: ${key}`);
    const delta = obj.delta;
    let content: ChatItem = existing.content;
    if (
      delta.kind === "text" &&
      (content.kind === "text" || content.kind === "reasoning")
    ) {
      content =
        content.kind === "text"
          ? {
              ...content,
              text: content.text + delta.text,
              citations: [...content.citations, ...delta.citations],
            }
          : { ...content, text: content.text + delta.text };
    } else if (delta.kind === "tool_arguments" && content.kind === "tool") {
      const args = { ...content.arguments };
      for (const [name, value] of Object.entries(delta.arguments)) {
        const previous = args[name];
        args[name] = (typeof previous === "string" ? previous : "") + value;
      }
      content = { ...content, arguments: args };
    } else if (delta.kind === "tool_output" && content.kind === "tool") {
      content = {
        ...content,
        output: delta.output ?? content.output,
        metadata: delta.metadata ?? content.metadata,
      };
    } else {
      throw new Error(`Invalid ${delta.kind} delta for ${content.kind}`);
    }
    this.items.set(key, { ...existing, content });
  }
}

export function toolMetadata<K extends ToolMetadata["type"]>(
  items: ResponseItem[],
  type: K
): Extract<ToolMetadata, { type: K }>[] {
  return items
    .flatMap((item) =>
      item.content.kind === "tool" && item.content.metadata
        ? [item.content.metadata]
        : []
    )
    .filter(
      (metadata): metadata is Extract<ToolMetadata, { type: K }> =>
        metadata.type === type
    );
}

export function firstTool(items: ResponseItem[]): ToolItem | undefined {
  return items
    .map((item) => item.content)
    .find((content): content is ToolItem => content.kind === "tool");
}

export function stringArgument(
  tool: ToolItem | undefined,
  name: string
): string {
  const value = tool?.arguments[name];
  return typeof value === "string" ? value : "";
}

export function isComplete(items: ResponseItem[]): boolean {
  return (
    items.length > 0 &&
    items.every(
      (item) =>
        item.content.status !== "running" && item.content.status !== "pending"
    )
  );
}

export function textContent(
  items: ResponseItem[],
  purpose: "answer" | "plan" | "report" | "commentary" = "answer"
): string {
  return items
    .map((item) =>
      item.content.kind === "text" && item.content.purpose === purpose
        ? item.content.text
        : ""
    )
    .join("");
}

export function displayType(items: ResponseItem[]): string | undefined {
  const item = items[0]?.content;
  if (!item) return undefined;
  if (item.kind === "text") return item.purpose;
  if (item.kind === "reasoning") return item.kind;
  switch (item.name) {
    case "python":
      return "run_python";
    case "internal_search":
    case "web_search":
    case "run_python":
    case "open_url":
    case "generate_image":
    case "research_agent":
    case "coding_agent":
    case "bash":
    case "add_memory":
    case "read_file":
      return item.name;
    default:
      return "custom";
  }
}

/** Close unfinished cached work when its worker no longer refreshes the processing marker. */
export function interruptResponse(packets: Packet[]): Packet[] {
  if (packets.some((packet) => packet.obj.type === "stop")) return packets;
  const runs = new Map<string, PacketIdentity>();
  for (const packet of packets) {
    if (!packet.identity) continue;
    if (packet.obj.type === "run_update" && packet.obj.status !== "running") {
      runs.delete(packet.identity.run_id);
    } else if (
      packet.obj.type === "item_update" ||
      packet.obj.type === "item_delta"
    ) {
      runs.set(packet.identity.run_id, packet.identity);
    }
  }
  const terminal: Packet[] = [...runs.values()].map((identity) => ({
    identity: { ...identity, part_id: "run", tool_call_id: null },
    obj: { type: "run_update", status: "error" },
  }));
  return [
    ...packets,
    ...terminal,
    { obj: { type: "stop", stop_reason: StopReason.INTERRUPTED } },
  ];
}
