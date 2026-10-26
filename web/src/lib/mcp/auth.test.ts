import { getMcpAuthenticationFlow } from "@/lib/mcp/auth";
import {
  type MCPAuthenticationServer,
  MCPConnectionStatus,
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
} from "@/lib/mcp/types";
const server: MCPAuthenticationServer = {
  id: 1,
  name: "Example",
  connection_status: MCPConnectionStatus.NOT_CONNECTED,
  auth_type: MCPAuthenticationType.OAUTH,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
};
describe("MCP authentication flow selection", () => {
  it.each([MCPAuthenticationType.NONE, MCPAuthenticationType.PT_OAUTH])(
    "does not offer a login for %s without required fields",
    (auth_type) => {
      expect(getMcpAuthenticationFlow({ ...server, auth_type })).toBeNull();
    }
  );
  it.each([
    MCPAuthenticationPerformer.ADMIN,
    MCPAuthenticationPerformer.PER_USER,
  ])("collects pass-through headers for %s", (auth_performer) => {
    expect(
      getMcpAuthenticationFlow({
        ...server,
        auth_performer,
        auth_type: MCPAuthenticationType.PT_OAUTH,
        auth_template: { headers: {}, required_fields: ["workspace"] },
      })
    ).toBe("credentials");
  });
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
