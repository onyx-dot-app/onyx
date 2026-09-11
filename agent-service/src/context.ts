import type {
  Message,
  Model,
  Api,
  TextContent,
  ImageContent,
} from "@earendil-works/pi-ai";
import type { PreparedContext } from "./protocol";

const emptyUsage = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};

/** Import persisted Onyx history. Native Pi messages retain signatures during a run. */
export function importContext(
  prepared: PreparedContext,
  model: Model<Api>,
  native: Message[],
) {
  const messages: Message[] = [];
  const systems: string[] = [];
  const tools = new Map<string, string>();
  const nativeCalls = new Map(
    native
      .filter((m) => m.role === "assistant")
      .flatMap((m) =>
        m.content.flatMap((c) =>
          c.type === "toolCall" ? [[c.id, m] as const] : [],
        ),
      ),
  );
  const nativeResults = new Map(
    native.filter((m) => m.role === "toolResult").map((m) => [m.toolCallId, m]),
  );
  for (const item of prepared.history) {
    const text =
      typeof item.content === "string"
        ? item.content
        : (item.content ?? [])
            .filter((c) => c.type === "text")
            .map((c) => c.text ?? "")
            .join("\n");
    if (item.role === "system" || item.role === "developer") {
      systems.push(text);
      continue;
    }
    if (item.role === "assistant") {
      for (const call of item.tool_calls ?? [])
        tools.set(call.id, call.function.name);
      const original =
        item.tool_calls?.[0] && nativeCalls.get(item.tool_calls[0].id);
      messages.push(
        original ?? {
          role: "assistant",
          content: [
            ...(text ? [{ type: "text" as const, text }] : []),
            ...(item.tool_calls ?? []).map((call) => ({
              type: "toolCall" as const,
              id: call.id,
              name: call.function.name,
              arguments: JSON.parse(call.function.arguments) as Record<
                string,
                unknown
              >,
            })),
          ],
          api: model.api,
          provider: model.provider,
          model: model.id,
          usage: emptyUsage,
          stopReason: item.tool_calls?.length ? "toolUse" : "stop",
          timestamp: 0,
        },
      );
    } else if (item.role === "tool") {
      if (!item.tool_call_id || !tools.has(item.tool_call_id))
        throw new Error("Orphaned tool result");
      messages.push({
        role: "toolResult",
        toolCallId: item.tool_call_id,
        toolName: tools.get(item.tool_call_id)!,
        content: [{ type: "text", text }],
        isError: nativeResults.get(item.tool_call_id)?.isError ?? false,
        timestamp: 0,
      });
    } else {
      const content: (TextContent | ImageContent)[] = [];
      if (typeof item.content === "string")
        content.push({ type: "text", text });
      else
        for (const block of item.content ?? []) {
          if (block.type === "text")
            content.push({ type: "text", text: block.text ?? "" });
          else if (block.type === "image_url") {
            const match = /^data:([^;]+);base64,(.+)$/s.exec(
              block.image_url?.url ?? "",
            );
            if (!match)
              throw new Error("History images must contain inline data");
            content.push({
              type: "image",
              mimeType: match[1]!,
              data: match[2]!,
            });
          } else throw new Error(`Unsupported history content: ${block.type}`);
        }
      messages.push({ role: "user", content, timestamp: 0 });
    }
  }
  return { systemPrompt: systems.join("\n\n"), messages };
}
