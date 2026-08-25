import {
  getMCPUserOAuthNavigationUrl,
  MCPUserOAuthStartResponse,
  startMCPUserOAuth,
} from "@/lib/tools/svc";

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
