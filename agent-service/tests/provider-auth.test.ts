import { expect, test } from "bun:test";
import { resolveProvider } from "../src/providers";
import type { Start } from "../src/protocol";

function start(provider: string, options: Record<string, unknown> = {}): Start {
  return {
    type: "start",
    allowWorkloadIdentity: false,
    config: {
      model_provider: provider,
      model_name: "test-model",
      api_key: null,
      api_base: "https://example.invalid/v1",
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

test("provider options do not expose tenant environment selectors to SDKs", () => {
  const request = start("bedrock", {
    aws_access_key_id: "tenant-access",
    aws_secret_access_key: "tenant-secret",
    aws_region_name: "us-west-2",
  });
  request.config.custom_config = {
    AWS_PROFILE: "another-tenant",
    GOOGLE_APPLICATION_CREDENTIALS: "/another-tenant/credentials.json",
    HTTPS_PROXY: "https://example.invalid",
    AWS_BEDROCK_SKIP_AUTH: "1",
    AWS_SESSION_TOKEN: "unmapped-token",
  };
  expect(resolveProvider(request).options.env).toEqual({
    AWS_ACCESS_KEY_ID: "tenant-access",
    AWS_SECRET_ACCESS_KEY: "tenant-secret",
    AWS_REGION: "us-west-2",
  });
});

test("Bedrock rejects incomplete credentials even when a bearer token is present", () => {
  for (const options of [
    { aws_access_key_id: "tenant-access" },
    { aws_secret_access_key: "tenant-secret" },
    { aws_session_token: "tenant-session" },
    { aws_access_key_id: "tenant-access", api_key: "tenant-bearer" },
  ]) {
    expect(() => resolveProvider(start("bedrock", options))).toThrow(
      "complete per-run AWS credential pair",
    );
  }
});

test("Bedrock accepts explicit bearer auth without a cloud credential chain", () => {
  const resolved = resolveProvider(
    start("bedrock", { api_key: "tenant-bearer" }),
  );
  expect(resolved.options.apiKey).toBe("tenant-bearer");
  expect(resolved.options.env).toEqual({ AWS_REGION: "us-east-1" });
});

test("missing credentials never imply workload identity or an API key", () => {
  expect(() => resolveProvider(start("bedrock"))).toThrow(
    "per-run credentials",
  );
  for (const provider of ["openai", "anthropic", "gemini", "azure"]) {
    expect(() => resolveProvider(start(provider))).toThrow(
      "explicit per-run authentication",
    );
  }
});

test("concurrent provider requests retain their own authorization headers", async () => {
  const observed = new Map<string, string | null>();
  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      const body = (await request.json()) as { model: string };
      await new Promise((resolve) =>
        setTimeout(resolve, body.model === "first" ? 20 : 1),
      );
      observed.set(body.model, request.headers.get("authorization"));
      return new Response(
        `data: ${JSON.stringify({ id: body.model, object: "chat.completion.chunk", created: 1, model: body.model, choices: [{ index: 0, delta: { role: "assistant", content: "ok" }, finish_reason: "stop" }] })}\n\ndata: [DONE]\n\n`,
        { headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  try {
    await Promise.all(
      ["first", "second"].map(async (tenant) => {
        const request = start("openai", { api_key: `${tenant}-key` });
        request.apiSurface = "openai_chat_completions";
        request.config.model_name = tenant;
        request.config.api_base = server.url.toString();
        const resolved = resolveProvider(request);
        const response = await resolved
          .stream(
            resolved.model,
            {
              messages: [
                { role: "user", content: "hello", timestamp: Date.now() },
              ],
            },
            resolved.options,
          )
          .result();
        expect(response.stopReason).toBe("stop");
      }),
    );
    expect(observed).toEqual(
      new Map([
        ["second", "Bearer second-key"],
        ["first", "Bearer first-key"],
      ]),
    );
  } finally {
    server.stop(true);
  }
});

test("workload identity requires independent host and operator authorization", async () => {
  const request = start("bedrock");
  request.config.custom_config = { BEDROCK_AUTH_METHOD: "iam" };
  const script = `
    import { startSchema } from './src/protocol';
    import { resolveProvider } from './src/providers';
    const request = ${JSON.stringify(request)};
    delete request.allowWorkloadIdentity;
    const parsed = startSchema.parse(request);
    if (parsed.allowWorkloadIdentity !== false) throw new Error('unsafe default');
    let denied = false;
    try { resolveProvider(parsed); } catch { denied = true; }
    if (!denied) throw new Error('operator flag bypassed host policy');
    parsed.allowWorkloadIdentity = true;
    resolveProvider(parsed);
    delete parsed.config.custom_config.BEDROCK_AUTH_METHOD;
    denied = false;
    try { resolveProvider(parsed); } catch { denied = true; }
    if (!denied) throw new Error('missing auth mode was accepted');
  `;
  const child = Bun.spawn([process.execPath, "-e", script], {
    cwd: new URL("..", import.meta.url).pathname,
    env: { ...process.env, ONYX_AGENT_ALLOW_WORKLOAD_IDENTITY: "true" },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [code, stderr] = await Promise.all([
    child.exited,
    new Response(child.stderr).text(),
  ]);
  expect({ code, stderr }).toEqual({ code: 0, stderr: "" });
});

test("Bedrock signing does not combine tenant keys with ambient AWS credentials", async () => {
  const request = start("bedrock", {
    aws_access_key_id: "tenant-access",
    aws_secret_access_key: "tenant-secret",
  });
  const script = `
    import { resolveProvider } from './src/providers';
    let observed;
    const server = Bun.serve({
      port: 0,
      fetch(request) {
        observed = { auth: request.headers.get('authorization'), token: request.headers.get('x-amz-security-token') };
        return new Response(JSON.stringify({ message: 'test rejection' }), { status: 400, headers: { 'content-type': 'application/json', 'x-amzn-errortype': 'ValidationException' } });
      }
    });
    try {
      const request = ${JSON.stringify(request)};
      request.config.api_base = server.url.toString();
      const resolved = resolveProvider(request);
      resolved.options.env.AWS_BEDROCK_FORCE_HTTP1 = '1';
      await resolved.stream(resolved.model, { messages: [{ role: 'user', content: 'hello', timestamp: Date.now() }] }, { ...resolved.options, maxRetries: 0 }).result();
      if (!observed?.auth?.includes('Credential=tenant-access/')) throw new Error('wrong identity');
      if (!observed.auth.includes('/us-east-1/bedrock/')) throw new Error('ambient region');
      if (observed.token !== null) throw new Error('ambient session token');
    } finally { server.stop(true); }
  `;
  const child = Bun.spawn([process.execPath, "-e", script], {
    cwd: new URL("..", import.meta.url).pathname,
    env: {
      ...process.env,
      AWS_ACCESS_KEY_ID: "ambient-access",
      AWS_SECRET_ACCESS_KEY: "ambient-secret",
      AWS_SESSION_TOKEN: "ambient-token",
      AWS_REGION: "eu-west-1",
      AWS_PROFILE: "profile-that-must-never-be-loaded",
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
