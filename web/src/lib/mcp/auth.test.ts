import {
  canAuthenticateMcpServer,
  type MCPAuthenticationServer,
} from "@/lib/mcp/auth";
import {
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
