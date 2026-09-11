import { test, expect } from "bun:test";
import { ChatRun } from "../src/run";
import type { Host, Start } from "../src/protocol";

function config(base: string): Start {
  return {
    type: "start",
    config: {
      model_provider: "openai",
      model_name: "gpt-5-mini",
      api_key: "tenant-key",
      api_base: base,
      api_version: null,
      deployment_name: null,
      custom_config: null,
      temperature: 1,
      max_input_tokens: 32000,
      reasoning_effort_default: null,
      reasoning_effort_user_default: null,
      reasoning_effort_max: null,
    },
    apiSurface: "openai_chat_completions",
    options: {},
    reasoningEffort: "off",
    maxTurns: 4,
    sessionId: null,
  };
}

test("Pi executes parallel tools and follows up through the provider API", async () => {
  const requests: Record<string, unknown>[] = [];
  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      expect(req.headers.get("authorization")).toBe("Bearer tenant-key");
      const payload = (await req.json()) as Record<string, unknown>;
      requests.push(payload);
      const delta =
        requests.length === 1
          ? {
              role: "assistant",
              tool_calls: [
                {
                  index: 0,
                  id: "call_a",
                  type: "function",
                  function: { name: "search", arguments: '{"query":"alpha"}' },
                },
                {
                  index: 1,
                  id: "call_b",
                  type: "function",
                  function: { name: "search", arguments: '{"query":"beta"}' },
                },
              ],
            }
          : { role: "assistant", content: "The answer [1]." };
      const chunk = (d: unknown, reason: string | null) =>
        `data: ${JSON.stringify({ id: "completion", object: "chat.completion.chunk", created: 1, model: "gpt-5-mini", choices: [{ index: 0, delta: d, finish_reason: reason }] })}\n\n`;
      return new Response(
        chunk(delta, null) +
          chunk({}, requests.length === 1 ? "tool_calls" : "stop") +
          "data: [DONE]\n\n",
        { headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  const events: Record<string, unknown>[] = [];
  const batches: unknown[] = [];
  const host: Host = {
    send(event) {
      events.push(event);
    },
    async request(type, payload) {
      if (type === "model_start" || type === "turn_end") return null;
      if (type === "tools") {
        batches.push(payload?.calls);
        return { call_a: "alpha evidence", call_b: "beta evidence" };
      }
      if (type === "prepare")
        return {
          history: [
            { role: "user", content: "search both" },
            ...(payload?.cycle
              ? [
                  {
                    role: "assistant",
                    content: "",
                    tool_calls: [
                      {
                        id: "call_a",
                        function: {
                          name: "search",
                          arguments: '{"query":"alpha"}',
                        },
                      },
                      {
                        id: "call_b",
                        function: {
                          name: "search",
                          arguments: '{"query":"beta"}',
                        },
                      },
                    ],
                  },
                  {
                    role: "tool",
                    tool_call_id: "call_a",
                    content: "alpha evidence",
                  },
                  {
                    role: "tool",
                    tool_call_id: "call_b",
                    content: "beta evidence",
                  },
                  { role: "user", content: "Cite evidence." },
                ]
              : []),
          ],
          tools: [
            {
              type: "function",
              function: {
                name: "search",
                description: "Search",
                parameters: {
                  type: "object",
                  properties: { query: { type: "string" } },
                  required: ["query"],
                },
              },
            },
          ],
          toolChoice: payload?.cycle ? "auto" : "required",
        };
      throw new Error(type);
    },
  };
  try {
    await new ChatRun(
      config(`http://127.0.0.1:${server.port}/v1`),
      host,
    ).execute();
    expect(requests).toHaveLength(2);
    expect(requests[0]?.tool_choice).toBe("required");
    expect(batches).toHaveLength(1);
    expect(batches[0]).toEqual([
      {
        type: "toolCall",
        id: "call_a",
        name: "search",
        arguments: { query: "alpha" },
      },
      {
        type: "toolCall",
        id: "call_b",
        name: "search",
        arguments: { query: "beta" },
      },
    ]);
    expect(JSON.stringify(requests[1])).toContain("Cite evidence.");
    expect(events.at(-1)).toEqual({ type: "done" });
    expect(JSON.stringify(events)).toContain("The answer [1].");
  } finally {
    server.stop(true);
  }
});

function textHost(
  prompt: string,
  output: Record<string, unknown>[],
  forceTool = false,
): Host {
  return {
    send(event) {
      output.push(event);
    },
    async request(type) {
      if (type === "prepare")
        return {
          history: [{ role: "user", content: prompt }],
          tools: forceTool
            ? [
                {
                  type: "function",
                  function: {
                    name: "search",
                    parameters: { type: "object", properties: {} },
                  },
                },
              ]
            : [],
          toolChoice: forceTool ? "required" : "auto",
        };
      if (type === "model_start") return null;
      throw new Error(`Unexpected callback ${type}`);
    },
  };
}

function sse(events: Record<string, unknown>[]): Response {
  return new Response(
    events
      .map(
        (event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
      )
      .join(""),
    {
      headers: { "content-type": "text/event-stream" },
    },
  );
}

test("concurrent OpenAI, Anthropic and Vertex runs keep credentials and streams separate", async () => {
  const requests: { path: string; credential: string | null; body: unknown }[] =
    [];
  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      const path = new URL(request.url).pathname;
      requests.push({
        path,
        credential:
          request.headers.get("authorization") ??
          request.headers.get("x-api-key"),
        body: await request.json(),
      });
      if (path.endsWith("/messages") || path.endsWith(":streamRawPredict"))
        return sse([
          {
            type: "message_start",
            message: {
              id: "anthropic",
              type: "message",
              role: "assistant",
              model: "claude-haiku-4-5",
              content: [],
              stop_reason: null,
              stop_sequence: null,
              usage: { input_tokens: 10, output_tokens: 0 },
            },
          },
          {
            type: "content_block_start",
            index: 0,
            content_block: { type: "text", text: "" },
          },
          {
            type: "content_block_delta",
            index: 0,
            delta: { type: "text_delta", text: "Anthropic tenant answer" },
          },
          { type: "content_block_stop", index: 0 },
          {
            type: "message_delta",
            delta: { stop_reason: "end_turn", stop_sequence: null },
            usage: { output_tokens: 4 },
          },
          { type: "message_stop" },
        ]);
      const message = {
        id: "msg_1",
        type: "message",
        role: "assistant",
        status: "completed",
        content: [
          {
            type: "output_text",
            text: "OpenAI tenant answer",
            annotations: [],
          },
        ],
      };
      return sse([
        {
          type: "response.created",
          response: {
            id: "resp_1",
            status: "in_progress",
            model: "gpt-5-mini",
            output: [],
          },
        },
        {
          type: "response.output_item.added",
          output_index: 0,
          item: { ...message, status: "in_progress", content: [] },
        },
        {
          type: "response.content_part.added",
          item_id: "msg_1",
          output_index: 0,
          content_index: 0,
          part: { type: "output_text", text: "", annotations: [] },
        },
        {
          type: "response.output_text.delta",
          item_id: "msg_1",
          output_index: 0,
          content_index: 0,
          delta: "OpenAI tenant answer",
        },
        { type: "response.output_item.done", output_index: 0, item: message },
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            status: "completed",
            model: "gpt-5-mini",
            output: [message],
            usage: {
              input_tokens: 10,
              output_tokens: 4,
              total_tokens: 14,
              input_tokens_details: { cached_tokens: 0 },
              output_tokens_details: { reasoning_tokens: 0 },
            },
          },
        },
      ]);
    },
  });
  const openai = config(`http://127.0.0.1:${server.port}/v1`);
  openai.apiSurface = null;
  openai.config.api_key = "openai-tenant";
  const anthropic = config(`http://127.0.0.1:${server.port}`);
  anthropic.apiSurface = null;
  anthropic.reasoningEffort = "medium";
  anthropic.config.model_provider = "anthropic";
  anthropic.config.model_name = "claude-haiku-4-5";
  anthropic.config.api_key = "anthropic-tenant";
  const vertex = config(`http://127.0.0.1:${server.port}/v1`);
  vertex.apiSurface = null;
  vertex.config.model_provider = "vertex_ai";
  vertex.config.model_name = "claude-haiku-4-5@20251001";
  vertex.options = {
    vertex_project: "vertex-tenant",
    vertex_location: "us-east5",
    vertex_access_token: "vertex-token",
  };
  const third: Record<string, unknown>[] = [];
  const first: Record<string, unknown>[] = [],
    second: Record<string, unknown>[] = [];
  try {
    await Promise.all([
      new ChatRun(openai, textHost("openai-private-prompt", first)).execute(),
      new ChatRun(vertex, textHost("vertex-private-prompt", third)).execute(),
      new ChatRun(
        anthropic,
        textHost("anthropic-private-prompt", second, true),
      ).execute(),
    ]);
    expect(requests).toHaveLength(3);
    expect(
      requests.find((r) => r.path.endsWith(":streamRawPredict")),
    ).toMatchObject({
      path: "/v1/projects/vertex-tenant/locations/us-east5/publishers/anthropic/models/claude-haiku-4-5@20251001:streamRawPredict",
      credential: "Bearer vertex-token",
      body: { anthropic_version: "vertex-2023-10-16" },
    });
    expect(JSON.stringify(third)).toContain("Anthropic tenant answer");
    expect(
      requests.find((r) => r.path.endsWith("/responses"))?.credential,
    ).toBe("Bearer openai-tenant");
    expect(requests.find((r) => r.path.endsWith("/messages"))?.credential).toBe(
      "anthropic-tenant",
    );
    expect(
      requests.find((r) => r.path.endsWith("/messages"))?.body,
    ).toMatchObject({
      thinking: { type: "disabled" },
      tool_choice: { type: "any" },
    });
    expect(JSON.stringify(first)).toContain("OpenAI tenant answer");
    expect(JSON.stringify(first)).not.toContain("Anthropic tenant answer");
    expect(JSON.stringify(second)).toContain("Anthropic tenant answer");
    expect(
      JSON.stringify(requests.find((r) => r.path.endsWith("/messages"))?.body),
    ).not.toContain("openai-private-prompt");
  } finally {
    server.stop(true);
  }
});

test("invalid tool arguments return to the model and the turn limit removes tools", async () => {
  const requests: Record<string, unknown>[] = [];
  let results: {
    toolCallId: string;
    content: { text: string }[];
    isError: boolean;
  }[] = [];
  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      requests.push((await request.json()) as Record<string, unknown>);
      const first = requests.length === 1;
      const delta = first
        ? {
            role: "assistant",
            tool_calls: [
              {
                index: 0,
                id: "bad_call",
                type: "function",
                function: { name: "search", arguments: '{"query":42}' },
              },
            ],
          }
        : { role: "assistant", content: "Unable to search." };
      return new Response(
        `data: ${JSON.stringify({ id: "completion", object: "chat.completion.chunk", created: 1, model: "gpt-5-mini", choices: [{ index: 0, delta, finish_reason: first ? "tool_calls" : "stop" }] })}\n\ndata: [DONE]\n\n`,
        { headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  const options = config(`http://127.0.0.1:${server.port}/v1`);
  options.maxTurns = 2;
  const events: Record<string, unknown>[] = [];
  const host: Host = {
    send(event) {
      events.push(event);
    },
    async request(type, payload) {
      if (type === "model_start") return null;
      if (type === "tools")
        throw new Error("Invalid arguments reached host execution");
      if (type === "turn_end") {
        results = payload?.results as typeof results;
        return null;
      }
      if (type === "prepare")
        return {
          history: [
            { role: "user", content: "Search" },
            ...(payload?.cycle
              ? [
                  {
                    role: "assistant",
                    content: "",
                    tool_calls: [
                      {
                        id: "bad_call",
                        function: { name: "search", arguments: '{"query":42}' },
                      },
                    ],
                  },
                  {
                    role: "tool",
                    tool_call_id: "bad_call",
                    content: results[0]?.content.map((c) => c.text).join("\n"),
                  },
                ]
              : []),
          ],
          tools: [
            {
              type: "function",
              function: {
                name: "search",
                parameters: {
                  type: "object",
                  properties: { query: { type: "string" } },
                  required: ["query"],
                },
              },
            },
          ],
          toolChoice: "required",
        };
      throw new Error(type);
    },
  };
  try {
    await new ChatRun(options, host).execute();
    expect(results).toHaveLength(1);
    expect(results[0]?.isError).toBe(true);
    expect(requests).toHaveLength(2);
    expect(requests[1]?.tools).toEqual([]);
    expect(JSON.stringify(requests[1]?.messages)).toContain("query");
    expect(events.at(-1)).toEqual({ type: "done" });
  } finally {
    server.stop(true);
  }
});
