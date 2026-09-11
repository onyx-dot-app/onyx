import {
  Agent,
  type AgentTool,
  type AgentMessage,
} from "@earendil-works/pi-agent-core";
import type {
  Message,
  AssistantMessage,
  ToolCall,
} from "@earendil-works/pi-ai";
import type { TSchema } from "typebox";
import { z } from "zod";
import {
  contextSchema,
  type Host,
  type Start,
  type PreparedContext,
} from "./protocol";
import { resolveProvider } from "./providers";
import { ModelFailure } from "./errors";
import { prepareCredentials } from "./credentials";
import { importContext } from "./context";

/** A run owns its model, credentials, transcript, tools and cancellation signal. */
export class ChatRun {
  private agent?: Agent;
  private cancelled = false;
  constructor(
    private readonly start: Start,
    private readonly host: Host,
  ) {}

  abort() {
    this.cancelled = true;
    this.agent?.abort();
  }

  async execute() {
    const resolved = resolveProvider(this.start);
    const cleanup =
      resolved.model.api === "google-vertex"
        ? await prepareCredentials(this.start, resolved.options)
        : async () => {};
    try {
      await this.runAgent(resolved);
    } finally {
      await cleanup();
    }
  }

  private async runAgent({
    model,
    stream,
    options,
    body,
  }: ReturnType<typeof resolveProvider>) {
    let cycle = 0;
    let responseStatus: number | undefined;
    let modelFailure: ModelFailure | undefined;
    let prepared: PreparedContext;
    let batch: Promise<Record<string, string>> | undefined;
    let pending: ToolCall[] = [];
    let renderBarrier: Promise<unknown> | undefined;
    const makeTools = (context: PreparedContext): AgentTool[] =>
      context.tools.map(({ function: tool }) => ({
        name: tool.name,
        label: tool.name,
        description: tool.description ?? "",
        parameters: tool.parameters as TSchema,
        execute: async (id, args) => {
          pending.push({
            type: "toolCall",
            id,
            name: tool.name,
            arguments: z.record(z.string(), z.unknown()).parse(args),
          });
          // Pi validates each call first. Collect this batch before crossing the host boundary.
          batch ??= new Promise<void>((resolve) => setTimeout(resolve, 0)).then(
            async () => {
              batch = undefined;
              const calls = pending;
              pending = [];
              return z
                .record(z.string(), z.string())
                .parse(await this.host.request("tools", { calls }));
            },
          );
          const results = await batch;
          if (!(id in results))
            throw new Error(`Host omitted tool result ${id}`);
          return {
            content: [{ type: "text", text: results[id]! }],
            details: {},
          };
        },
      }));
    const prepare = async (native: AgentMessage[]) => {
      if (this.cancelled) throw new Error("Run cancelled");
      prepared = contextSchema.parse(
        await this.host.request("prepare", { cycle }),
      );
      if (cycle >= this.start.maxTurns - 1)
        prepared = { ...prepared, tools: [], toolChoice: "none" };
      const imported = importContext(prepared, model, native as Message[]);
      return { ...imported, tools: makeTools(prepared) };
    };
    const context = await prepare([]);
    const thinkingLevel = z
      .enum(["off", "minimal", "low", "medium", "high", "xhigh", "max"])
      .parse(this.start.reasoningEffort);
    this.agent = new Agent({
      initialState: { ...context, model, thinkingLevel },
      streamFn: (currentModel, currentContext, agentOptions) => {
        responseStatus = undefined;
        return stream(currentModel, currentContext, {
          ...agentOptions,
          ...options,
          signal: agentOptions?.signal,
          onResponse: (response) => {
            responseStatus = response.status;
          },
          onPayload: (payload) => {
            const output = {
              ...z.record(z.string(), z.unknown()).parse(payload),
              ...body,
            };
            if (prepared.toolChoice === "required") {
              if (model.api === "anthropic-messages") {
                output.tool_choice = { type: "any" };
                output.thinking = { type: "disabled" };
                delete output.output_config;
              } else if (model.api.startsWith("google")) {
                const config = z
                  .record(z.string(), z.unknown())
                  .parse(output.config ?? {});
                output.config = {
                  ...config,
                  toolConfig: { functionCallingConfig: { mode: "ANY" } },
                };
              } else if (model.api === "bedrock-converse-stream") {
                const config = z
                  .record(z.string(), z.unknown())
                  .parse(output.toolConfig ?? {});
                output.toolConfig = { ...config, toolChoice: { any: {} } };
              } else output.tool_choice = "required";
            }
            return output;
          },
        });
      },
      prepareNextTurnWithContext: async ({ context }) => {
        cycle++;
        batch = undefined;
        return { context: await prepare(context.messages) };
      },
      shouldStopAfterTurn: () => cycle >= this.start.maxTurns - 1,
    });
    this.agent.subscribe(async (event) => {
      if (
        event.type === "message_start" &&
        event.message.role === "assistant"
      ) {
        // Do not await until model_end: the host reads the stream inside its renderer.
        renderBarrier = this.host.request("model_start");
      } else if (event.type === "turn_end" && event.toolResults.length) {
        await this.host.request("turn_end", { results: event.toolResults });
      } else if (event.type === "message_update") {
        const delta = event.assistantMessageEvent;
        if (delta.type === "text_delta") this.chunk({ content: delta.delta });
        if (
          delta.type === "toolcall_start" ||
          delta.type === "toolcall_delta"
        ) {
          const call = delta.partial.content[delta.contentIndex];
          if (call?.type === "toolCall") {
            const index =
              delta.partial.content
                .slice(0, delta.contentIndex + 1)
                .filter((c) => c.type === "toolCall").length - 1;
            this.chunk({
              tool_calls: [
                {
                  id: call.id,
                  index,
                  type: "function",
                  function: {
                    name: call.name,
                    arguments:
                      delta.type === "toolcall_delta" ? delta.delta : "",
                  },
                },
              ],
            });
          }
        }
        if (delta.type === "thinking_delta")
          this.chunk({ reasoning_content: delta.delta });
      } else if (
        event.type === "message_end" &&
        event.message.role === "assistant"
      ) {
        const message = event.message;
        if (message.stopReason === "error" || message.stopReason === "aborted")
          modelFailure = new ModelFailure(
            message.errorMessage ?? `Model ${message.stopReason}`,
            responseStatus,
          );
        this.finishMessage(message);
        this.host.send({ type: "model_end" });
        await renderBarrier;
      }
    });
    if (this.cancelled) this.agent.abort();
    else await this.agent.continue();
    if (modelFailure) throw modelFailure;
    if (this.agent.state.errorMessage)
      throw new ModelFailure(this.agent.state.errorMessage, responseStatus);
    if (this.cancelled) throw new Error("Run cancelled");
    this.host.send({ type: "done" });
  }

  private chunk(
    delta: Record<string, unknown>,
    finishReason: string | null = null,
    usage?: Record<string, number>,
  ) {
    this.host.send({
      type: "chunk",
      chunk: {
        id: "pi",
        created: String(Date.now()),
        choice: { index: 0, delta, finish_reason: finishReason },
        usage,
      },
    });
  }

  private finishMessage(message: AssistantMessage) {
    const calls = message.content.filter((block) => block.type === "toolCall");
    this.chunk(
      {
        tool_calls: calls.map((call, index) => ({
          id: call.id,
          index,
          type: "function",
          function: {
            name: call.name,
            arguments: JSON.stringify(call.arguments),
          },
        })),
      },
      calls.length
        ? "tool_calls"
        : (message.rawStopReason ??
            (message.stopReason === "length" ? "length" : "stop")),
      {
        prompt_tokens:
          message.usage.input +
          message.usage.cacheRead +
          message.usage.cacheWrite,
        completion_tokens: message.usage.output,
        total_tokens: message.usage.totalTokens,
        cache_read_input_tokens: message.usage.cacheRead,
        cache_creation_input_tokens: message.usage.cacheWrite,
      },
    );
  }
}
