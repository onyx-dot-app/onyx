import {
  discoverMCPOAuth,
  MCPOAuthError,
  getMCPUserOAuthNavigationUrl,
  MCPUserOAuthStartResponse,
  refreshMCPServerTools,
  streamMCPServerProbe,
  startMCPAdminOAuth,
  startMCPUserOAuth,
} from "@/lib/mcp/svc";

describe("MCP OAuth start", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test.each<{
    name: string;
    forceReauthentication: boolean;
    response: MCPUserOAuthStartResponse;
    expectedNavigation: string;
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
      expectedNavigation: "https://accounts.example.com/authorize",
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
      expectedNavigation: "/app",
    },
  ])(
    "$name",
    async ({ forceReauthentication, response, expectedNavigation }) => {
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
      expect(getMCPUserOAuthNavigationUrl(result)).toBe(expectedNavigation);
    }
  );
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

  test("admin authorization preserves credential change flags", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "already_authenticated",
          server_id: 42,
          authorization_url: null,
          redirect_url: "/admin/mcp-actions",
        })
      )
    );

    const result = await startMCPAdminOAuth(42, "/admin/mcp-actions", {
      oauth_client_id: "saved-client",
      oauth_client_secret: "********",
      oauth_client_id_changed: false,
      oauth_client_secret_changed: false,
    });

    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/mcp/oauth/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        server_id: 42,
        return_path: "/admin/mcp-actions",
        include_resource_param: true,
        oauth_client_id: "saved-client",
        oauth_client_secret: "********",
        oauth_client_id_changed: false,
        oauth_client_secret_changed: false,
      }),
    });
    expect(getMCPUserOAuthNavigationUrl(result)).toBe("/admin/mcp-actions");
  });

  test("tool discovery exposes the server error without a JSON wrapper", async () => {
    jest.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error_code: "UNAUTHENTICATED",
          detail: "Sign in again",
        }),
        { status: 401 }
      )
    );
    await expect(refreshMCPServerTools(42)).rejects.toThrow("Sign in again");
  });

  test("OAuth startup handles non-JSON proxy errors", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(
        new Response("<html>Bad gateway</html>", { status: 502 })
      );
    await expect(startMCPAdminOAuth(42, "/admin/mcp-actions")).rejects.toThrow(
      "Could not start OAuth sign-in. Check the server settings and try again."
    );
  });
});

describe("MCP OAuth capability discovery", () => {
  afterEach(() => jest.restoreAllMocks());

  test("sends only the saved server ID and preserves capability results", async () => {
    const result = {
      status: "metadata_found",
      supports_automatic_registration: false,
      authorization_endpoint: "https://identity.example.com/authorize",
      token_endpoint: "https://identity.example.com/token",
    };
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(result)));
    await expect(discoverMCPOAuth(42)).resolves.toEqual(result);
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/mcp/oauth/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server_id: 42 }),
    });
  });

  test("rejects failed discovery without exposing proxy HTML", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(
        new Response("<html>private proxy data</html>", { status: 502 })
      );
    await expect(discoverMCPOAuth(42)).rejects.toThrow(
      "Could not check OAuth setup support"
    );
  });

  test("keeps the registration failure reason and hides embedded provider HTML", async () => {
    jest.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          oauth_error: "client_registration_failed",
          detail: "<html>private proxy data</html>",
        }),
        { status: 400 }
      )
    );
    const request = startMCPAdminOAuth(42, "/admin/mcp-actions");
    await expect(request).rejects.toBeInstanceOf(MCPOAuthError);
    await expect(request).rejects.toMatchObject({
      reason: "client_registration_failed",
      message:
        "Could not start OAuth sign-in. Check the server settings and try again.",
    });
  });
});
