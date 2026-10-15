import {
  canAuthenticateMcpServer,
  getMcpAuthenticationFlow,
  getMcpConnectionStatus,
} from "@/lib/mcp/auth";
import {
  type MCPAuthenticationServer,
  MCPConnectionStatus,
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
} from "@/lib/mcp/types";
const server: MCPAuthenticationServer = {
  id: 1,
  name: "Example",
  auth_type: MCPAuthenticationType.OAUTH,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
};
describe("chat MCP authentication affordances", () => {
  it.each([MCPAuthenticationType.OAUTH, MCPAuthenticationType.API_TOKEN])(
    "offers the per-user %s flow",
    (auth_type) => {
      expect(canAuthenticateMcpServer({ ...server, auth_type })).toBe(true);
    }
  );
  it.each([MCPAuthenticationType.OAUTH, MCPAuthenticationType.API_TOKEN])(
    "does not ask a user to repair shared %s credentials",
    (auth_type) => {
      expect(
        canAuthenticateMcpServer({
          ...server,
          auth_type,
          auth_performer: MCPAuthenticationPerformer.ADMIN,
          auth_template: { headers: {}, required_fields: ["token"] },
        })
      ).toBe(false);
    }
  );
  it("does not offer a separate login for pass-through OAuth", () => {
    expect(
      canAuthenticateMcpServer({
        ...server,
        auth_type: MCPAuthenticationType.PT_OAUTH,
      })
    ).toBe(false);
  });
  it.each([
    MCPAuthenticationPerformer.ADMIN,
    MCPAuthenticationPerformer.PER_USER,
  ])(
    "offers pass-through header values for %s without a separate login",
    (auth_performer) => {
      expect(
        canAuthenticateMcpServer({
          ...server,
          auth_performer,
          auth_type: MCPAuthenticationType.PT_OAUTH,
          auth_template: { headers: {}, required_fields: ["workspace"] },
        })
      ).toBe(true);
    }
  );
  it("offers required header values even when generated authentication is NONE", () => {
    expect(
      canAuthenticateMcpServer({
        ...server,
        auth_type: MCPAuthenticationType.NONE,
        auth_template: { headers: {}, required_fields: ["workspace"] },
      })
    ).toBe(true);
    expect(
      canAuthenticateMcpServer({
        ...server,
        auth_type: MCPAuthenticationType.NONE,
      })
    ).toBe(false);
  });
});

describe("MCP authentication flow selection", () => {
  it("starts OAuth directly when no credential fields are required", () => {
    expect(getMcpAuthenticationFlow(server)).toBe("oauth");
  });
  it.each([
    MCPAuthenticationType.API_TOKEN,
    MCPAuthenticationType.OAUTH,
    MCPAuthenticationType.NONE,
    MCPAuthenticationType.PT_OAUTH,
  ])("collects required fields before %s authentication", (auth_type) => {
    expect(
      getMcpAuthenticationFlow({
        ...server,
        auth_type,
        auth_template: { headers: {}, required_fields: ["workspace"] },
      })
    ).toBe("credentials");
  });
  it("collects an API key without a header template", () => {
    expect(
      getMcpAuthenticationFlow({
        ...server,
        auth_type: MCPAuthenticationType.API_TOKEN,
      })
    ).toBe("credentials");
  });
  it.each([MCPAuthenticationType.API_TOKEN, MCPAuthenticationType.OAUTH])(
    "does not select a flow for shared %s credentials",
    (auth_type) => {
      expect(
        getMcpAuthenticationFlow({
          ...server,
          auth_type,
          auth_performer: MCPAuthenticationPerformer.ADMIN,
          auth_template: { headers: {}, required_fields: ["workspace"] },
        })
      ).toBeNull();
    }
  );
});

describe("MCP connection status compatibility", () => {
  it("uses the explicit status when present", () => {
    expect(
      getMcpConnectionStatus({
        connection_status: MCPConnectionStatus.REAUTH_REQUIRED,
        user_can_authenticate: false,
      })
    ).toBe(MCPConnectionStatus.REAUTH_REQUIRED);
  });
  it("does not guess reauthentication from the old boolean", () => {
    expect(getMcpConnectionStatus({ user_can_authenticate: false })).toBe(
      MCPConnectionStatus.NOT_CONNECTED
    );
    expect(getMcpConnectionStatus({ user_can_authenticate: true })).toBe(
      MCPConnectionStatus.CONNECTED
    );
    expect(getMcpConnectionStatus({})).toBeUndefined();
  });
});
