import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ReactNode } from "react";
import { useMcpAuthentication } from "@/lib/mcp/hooks";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  type MCPServer,
} from "@/lib/mcp/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  getMCPUserOAuthNavigationUrl,
  saveMCPUserCredentials,
  startMCPUserOAuth,
} from "@/lib/mcp/svc";

jest.mock("@/lib/fetcher", () => ({ errorHandlingFetcher: jest.fn() }));
jest.mock("@/lib/mcp/svc", () => ({
  saveMCPUserCredentials: jest.fn(),
  startMCPUserOAuth: jest.fn(),
  getMCPUserOAuthNavigationUrl: jest.fn(),
}));

const server: Pick<
  MCPServer,
  "id" | "name" | "auth_type" | "auth_performer" | "auth_template"
> = {
  id: 5,
  name: "Example",
  auth_type: MCPAuthenticationType.OAUTH,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
};
function makeWrapper() {
  const cache = new Map();
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <SWRConfig value={{ provider: () => cache, dedupingInterval: 0 }}>
        {children}
      </SWRConfig>
    );
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(errorHandlingFetcher)
    .mockResolvedValue({ mcp_servers: [server] });
});

describe("useMcpAuthentication", () => {
  it("loads default agent 0 and shares refreshed credential state across chat surfaces", async () => {
    const { result } = renderHook(
      () => ({
        first: useMcpAuthentication(0),
        second: useMcpAuthentication(0),
      }),
      { wrapper: makeWrapper() }
    );
    await waitFor(() => expect(result.current.first.servers).toHaveLength(1));
    expect(errorHandlingFetcher).toHaveBeenCalledWith(
      "/api/mcp/servers/persona/0"
    );
    await act(() =>
      result.current.first.authenticate({
        ...server,
        auth_type: MCPAuthenticationType.API_TOKEN,
      })
    );
    jest.mocked(errorHandlingFetcher).mockResolvedValue({
      mcp_servers: [{ ...server, user_can_authenticate: true }],
    });
    await act(async () => {
      await result.current.first.submitCredentials({
        api_key: "test",
      });
    });
    expect(saveMCPUserCredentials).toHaveBeenCalledWith(
      5,
      { api_key: "test" },
      undefined
    );
    await waitFor(() =>
      expect(result.current.second.servers[0]?.user_can_authenticate).toBe(true)
    );
    expect(result.current.first.credentialRequest).toBeNull();
  });
  it.each([
    MCPAuthenticationPerformer.ADMIN,
    MCPAuthenticationPerformer.PER_USER,
  ])(
    "saves pass-through headers for %s without starting OAuth",
    async (auth_performer) => {
      const { result } = renderHook(() => useMcpAuthentication(0), {
        wrapper: makeWrapper(),
      });
      await act(() =>
        result.current.authenticate({
          ...server,
          auth_performer,
          auth_type: MCPAuthenticationType.PT_OAUTH,
          auth_template: { headers: {}, required_fields: ["workspace"] },
        })
      );
      expect(result.current.credentialRequest).not.toBeNull();
      await act(async () => {
        await result.current.submitCredentials({
          workspace: "example",
        });
      });
      expect(saveMCPUserCredentials).toHaveBeenCalledWith(
        5,
        { workspace: "example" },
        undefined
      );
      expect(startMCPUserOAuth).not.toHaveBeenCalled();
      expect(result.current.credentialRequest).toBeNull();
    }
  );
  it("keeps OAuth loading and blocks a second request while navigation is pending", async () => {
    jest.mocked(startMCPUserOAuth).mockResolvedValue({
      status: "authorization_required",
      server_id: server.id,
      authorization_url: "#oauth-provider",
      redirect_url: "/app",
    });
    jest
      .mocked(getMCPUserOAuthNavigationUrl)
      .mockReturnValue("#oauth-provider");
    const { result } = renderHook(() => useMcpAuthentication(0), {
      wrapper: makeWrapper(),
    });
    await act(() => result.current.authenticate(server));
    expect(result.current.loadingServerId).toBe(server.id);
    expect(window.location.hash).toBe("#oauth-provider");
    await act(() => result.current.authenticate(server));
    expect(startMCPUserOAuth).toHaveBeenCalledTimes(1);
    window.history.replaceState(null, "", "/");
  });
  it("surfaces OAuth failure and clears the pending state", async () => {
    const failure = new Error("Authorization unavailable");
    jest.mocked(startMCPUserOAuth).mockRejectedValue(failure);
    const { result } = renderHook(() => useMcpAuthentication(0), {
      wrapper: makeWrapper(),
    });
    await act(() => result.current.authenticate(server));
    expect(result.current.authenticationError).toBe(failure);
    expect(result.current.loadingServerId).toBeNull();
  });
  it("saves required headers before starting OAuth, retaining the form after failure", async () => {
    jest.mocked(startMCPUserOAuth).mockRejectedValue(new Error("Try again"));
    const { result } = renderHook(() => useMcpAuthentication(0), {
      wrapper: makeWrapper(),
    });
    await act(() =>
      result.current.authenticate({
        ...server,
        auth_template: { headers: {}, required_fields: ["workspace"] },
      })
    );
    expect(startMCPUserOAuth).not.toHaveBeenCalled();
    await act(async () => {
      await expect(
        result.current.submitCredentials({ workspace: "example" })
      ).rejects.toThrow("Try again");
    });
    expect(saveMCPUserCredentials).toHaveBeenCalledWith(
      5,
      { workspace: "example" },
      undefined
    );
    expect(startMCPUserOAuth).toHaveBeenCalled();
    expect(result.current.credentialRequest).not.toBeNull();
  });
});
