import {
  MCPUserOAuthStartResponse,
  streamMCPServerProbe,
  startMCPUserOAuth,
} from "@/lib/mcp/svc";
describe("MCP OAuth start", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("OAuth startup keeps its OAuth fallback for proxy errors", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(
        new Response("<html>Bad gateway</html>", { status: 502 })
      );
    await expect(startMCPUserOAuth(42, "/app")).rejects.toMatchObject({
      reason: "oauth_failed",
      message:
        "Could not start OAuth sign-in. Check the server settings and try again.",
    });
  });

  test.each<{
    name: string;
    forceReauthentication: boolean;
    response: MCPUserOAuthStartResponse;
  }>([
    {
      name: "opens provider authorization for a forced reconnect",
      forceReauthentication: true,
      response: {
        status: "authorization_required",
        server_id: 42,
        authorization_url: "https://accounts.example.com/authorize",
        redirect_url: "/app",
      },
    },
    {
      name: "returns internally when the existing grant is usable",
      forceReauthentication: false,
      response: {
        status: "already_authenticated",
        server_id: 42,
        authorization_url: null,
        redirect_url: "/app",
      },
    },
  ])("$name", async ({ forceReauthentication, response }) => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => response,
    } as Response);

    const result = await startMCPUserOAuth(42, "/app", {
      forceReauthentication,
    });

    expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/oauth/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        server_id: 42,
        return_path: "/app",
        include_resource_param: true,
        force_reauthentication: forceReauthentication,
      }),
    });
    expect(result).toEqual(response);
  });
});

describe("MCP setup requests", () => {
  afterEach(() => jest.restoreAllMocks());

  test("stream handles fragmented events and a final line without newline", async () => {
    const result = { kind: "auth_unknown", transport: null };
    const stream = [
      JSON.stringify({
        type: "progress",
        stage: "contacting_server",
        state: "success",
      }),
      JSON.stringify({
        type: "progress",
        stage: "authentication",
        state: "pending",
      }),
      JSON.stringify({ type: "result", result }),
    ].join("\n");
    const progress = jest.fn();
    jest.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start(controller) {
            for (let index = 0; index < stream.length; index += 7)
              controller.enqueue(
                new TextEncoder().encode(stream.slice(index, index + 7))
              );
            controller.close();
          },
        })
      )
    );
    expect(
      await streamMCPServerProbe("https://mcp.example/mcp", progress)
    ).toEqual(result);
    expect(progress.mock.calls.map(([event]) => event.state)).toEqual([
      "success",
      "pending",
    ]);
  });

  test.each([
    "{broken}\n",
    '{"type":"progress","stage":"fake","state":"pending"}\n',
    '{"type":"progress","stage":"contacting_server","state":"pending"}\n',
  ])("rejects malformed or incomplete stream %s", async (body) => {
    jest.spyOn(global, "fetch").mockResolvedValueOnce(new Response(body));
    await expect(
      streamMCPServerProbe("https://mcp.example/mcp", jest.fn())
    ).rejects.toThrow();
  });
});
