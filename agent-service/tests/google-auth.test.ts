import { expect, test } from "bun:test";
import { readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { JWT, OAuth2Client } from "google-auth-library";
import { googleAuthentication } from "../src/google-auth";
import { resolveProvider } from "../src/providers";
import type { Start } from "../src/protocol";

function start(options: Record<string, unknown>): Start {
  return {
    type: "start",
    allowWorkloadIdentity: false,
    config: {
      model_provider: "vertex_ai",
      model_name: "gemini-2.5-flash",
      api_key: null,
      api_base: null,
      api_version: null,
      deployment_name: null,
      custom_config: null,
      temperature: 1,
      max_input_tokens: 32000,
      reasoning_effort_default: null,
      reasoning_effort_user_default: null,
      reasoning_effort_max: null,
    },
    options,
    apiSurface: null,
    reasoningEffort: "off",
    maxTurns: 4,
    sessionId: null,
  };
}

test("Google credential errors do not expose input or accept executable credential configurations", () => {
  const canary = "secret-that-must-not-appear";
  const invalid = [
    ...[
      "external_account",
      "authorized_user",
      "impersonated_service_account",
      "gdch_service_account",
    ].map((type) =>
      JSON.stringify({
        type,
        project_id: "tenant-project",
        client_email: "tenant@example.com",
        private_key: canary,
        credential_source: { file: `/tmp/${canary}` },
        token_url: `https://example.invalid/${canary}`,
      }),
    ),
    `{"type":"service_account","private_key":"${canary}",`,
    JSON.stringify({
      type: "service_account",
      private_key: canary,
      client_email: canary,
    }),
    canary.repeat(7000),
  ];
  for (const credentials of invalid) {
    let failure: unknown;
    try {
      googleAuthentication(start({ vertex_credentials: credentials }));
    } catch (error) {
      failure = error;
    }
    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).not.toContain(canary);
    expect((failure as Error).message).toBe(
      "Vertex credentials must contain a valid service-account email and private key",
    );
  }
});

test("Google service-account auth uses only in-memory key fields", async () => {
  const directoriesBefore = (await readdir(tmpdir()))
    .filter((name) => name.startsWith("onyx-agent-"))
    .sort();
  const auth = googleAuthentication(
    start({
      vertex_credentials: JSON.stringify({
        type: "service_account",
        project_id: "tenant-project",
        client_email: "tenant@example.com",
        private_key: "synthetic-test-key",
        credential_source: { file: "/path/that-must-not-be-opened" },
        token_uri: "https://example.invalid/token-that-must-not-be-used",
        universe_domain: "example.invalid",
        service_account_impersonation_url:
          "https://example.invalid/impersonate",
      }),
    }),
  );
  expect(auth.authClient).toBeInstanceOf(JWT);
  const client = auth.authClient as JWT;
  expect({
    email: client.email,
    key: client.key,
    keyFile: client.keyFile,
    subject: client.subject,
    project: auth.project,
  }).toEqual({
    email: "tenant@example.com",
    key: "synthetic-test-key",
    keyFile: undefined,
    subject: undefined,
    project: "tenant-project",
  });
  expect(client.endpoints.oauth2TokenUrl.toString()).toBe(
    "https://oauth2.googleapis.com/token",
  );
  expect(client.universeDomain).toBe("googleapis.com");
  expect(
    (await readdir(tmpdir()))
      .filter((name) => name.startsWith("onyx-agent-"))
      .sort(),
  ).toEqual(directoriesBefore);
});

test("Google access tokens stay in distinct auth clients and missing credentials fail closed", () => {
  const a = googleAuthentication(
    start({ vertex_project: "tenant-a", vertex_access_token: "token-a" }),
  );
  const b = googleAuthentication(
    start({ vertex_project: "tenant-b", vertex_access_token: "token-b" }),
  );
  expect(a.authClient).toBeInstanceOf(OAuth2Client);
  expect(a.authClient).not.toBe(b.authClient);
  expect(a.authClient?.credentials).toEqual({ access_token: "token-a" });
  expect(b.authClient?.credentials).toEqual({ access_token: "token-b" });
  expect(() =>
    googleAuthentication(start({ vertex_project: "tenant-a" })),
  ).toThrow("per-run credentials");
});

test("concurrent Vertex streams preserve each token, project and response without credential files", async () => {
  const before = (await readdir(tmpdir()))
    .filter((name) => name.startsWith("onyx-agent-"))
    .sort();
  const observed = new Map<string, string | null>();
  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      const path = new URL(request.url).pathname;
      const tenant = path.includes("tenant-a") ? "tenant-a" : "tenant-b";
      observed.set(tenant, request.headers.get("authorization"));
      await new Promise((resolve) =>
        setTimeout(resolve, tenant === "tenant-a" ? 20 : 1),
      );
      return new Response(
        `data: ${JSON.stringify({ candidates: [{ content: { role: "model", parts: [{ text: `response-for-${tenant}` }] }, finishReason: "STOP" }], usageMetadata: { promptTokenCount: 1, candidatesTokenCount: 1, totalTokenCount: 2 } })}\n\n`,
        { headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  try {
    const results = await Promise.all(
      ["tenant-a", "tenant-b"].map(async (tenant) => {
        const request = start({
          vertex_project: tenant,
          vertex_access_token: `token-for-${tenant}`,
        });
        request.config.api_base = server.url.toString();
        const resolved = resolveProvider(request);
        const result = await resolved
          .stream(
            resolved.model,
            {
              messages: [
                {
                  role: "user",
                  content: `hello-${tenant}`,
                  timestamp: Date.now(),
                },
              ],
            },
            resolved.options,
          )
          .result();
        expect(result.stopReason).toBe("stop");
        return result.content
          .filter((part) => part.type === "text")
          .map((part) => part.text)
          .join("");
      }),
    );
    expect(results).toEqual(["response-for-tenant-a", "response-for-tenant-b"]);
    expect(observed).toEqual(
      new Map([
        ["tenant-a", "Bearer token-for-tenant-a"],
        ["tenant-b", "Bearer token-for-tenant-b"],
      ]),
    );
    expect(
      (await readdir(tmpdir()))
        .filter((name) => name.startsWith("onyx-agent-"))
        .sort(),
    ).toEqual(before);
  } finally {
    server.stop(true);
  }
});

test("Vertex adapters ignore ambient endpoint and project configuration", async () => {
  const request = start({
    vertex_project: "tenant-project",
    vertex_location: "us-central1",
    vertex_access_token: "tenant-token",
  });
  const script = `
    import { resolveProvider } from './src/providers';
    const observed = [];
    globalThis.fetch = async (input, init) => {
      const request = new Request(input, init);
      observed.push({ url: request.url, authorization: request.headers.get('authorization') });
      const anthropic = request.url.includes('claude');
      const chunks = anthropic ? [
        { type: 'message_start', message: { id: 'test', type: 'message', role: 'assistant', model: 'claude-sonnet-4-6', content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 1, output_tokens: 0 } } },
        { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } },
        { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'ok' } },
        { type: 'content_block_stop', index: 0 },
        { type: 'message_delta', delta: { stop_reason: 'end_turn', stop_sequence: null }, usage: { output_tokens: 1 } },
        { type: 'message_stop' }
      ] : [{ candidates: [{ content: { role: 'model', parts: [{ text: 'ok' }] }, finishReason: 'STOP' }] }];
      return new Response(chunks.map((chunk) => (anthropic ? 'event: ' + chunk.type + '\\n' : '') + 'data: ' + JSON.stringify(chunk) + '\\n\\n').join(''), { headers: { 'content-type': 'text/event-stream' } });
    };
    const start = ${JSON.stringify(request)};
    for (const model of ['gemini-2.5-flash', 'claude-sonnet-4-6']) {
      start.config.model_name = model;
      const resolved = resolveProvider(start);
      const result = await resolved.stream(resolved.model, { messages: [{ role: 'user', content: 'hello', timestamp: Date.now() }] }, resolved.options).result();
      if (result.stopReason !== 'stop') throw new Error('mock stream did not complete: ' + result.errorMessage);
    }
    if (observed.length !== 2) throw new Error('unexpected transport calls');
    for (const request of observed) {
      const url = new URL(request.url);
      if (url.origin !== 'https://us-central1-aiplatform.googleapis.com') throw new Error('ambient endpoint selected');
      if (!url.pathname.includes('/projects/tenant-project/locations/us-central1/')) throw new Error('ambient project selected');
      if (request.authorization !== 'Bearer tenant-token') throw new Error('wrong credential');
    }
  `;
  const child = Bun.spawn([process.execPath, "-e", script], {
    cwd: new URL("..", import.meta.url).pathname,
    env: {
      ...process.env,
      ANTHROPIC_VERTEX_BASE_URL: "https://ambient-endpoint.invalid/v1",
      GOOGLE_VERTEX_BASE_URL: "https://ambient-endpoint.invalid/v1",
      ANTHROPIC_VERTEX_PROJECT_ID: "ambient-project",
      CLOUD_ML_REGION: "eu-west-1",
      GOOGLE_CLOUD_PROJECT: "ambient-project",
      GOOGLE_CLOUD_LOCATION: "europe-west1",
    },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [code, stderr] = await Promise.all([
    child.exited,
    new Response(child.stderr).text(),
  ]);
  expect({ code, stderr }).toEqual({ code: 0, stderr: "" });
});

test("Vertex express API keys remain explicit without project or cloud credentials", async () => {
  let observed:
    | { path: string; key: string | null; authorization: string | null }
    | undefined;
  const server = Bun.serve({
    port: 0,
    fetch(request) {
      observed = {
        path: new URL(request.url).pathname,
        key: request.headers.get("x-goog-api-key"),
        authorization: request.headers.get("authorization"),
      };
      return new Response(
        `data: ${JSON.stringify({ candidates: [{ content: { role: "model", parts: [{ text: "ok" }] }, finishReason: "STOP" }] })}\n\n`,
        { headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  try {
    const request = start({});
    request.config.api_key = "explicit-vertex-key";
    request.config.api_base = server.url.toString();
    const resolved = resolveProvider(request);
    const result = await resolved
      .stream(
        resolved.model,
        {
          messages: [{ role: "user", content: "hello", timestamp: Date.now() }],
        },
        resolved.options,
      )
      .result();
    expect(result.stopReason).toBe("stop");
    expect(observed).toEqual({
      path: "/v1/publishers/google/models/gemini-2.5-flash:streamGenerateContent",
      key: "explicit-vertex-key",
      authorization: null,
    });
  } finally {
    server.stop(true);
  }
});
