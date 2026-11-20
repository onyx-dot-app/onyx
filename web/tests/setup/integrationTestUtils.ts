import { makeAccess } from "@tests/setup/memberIntegrationTestUtils";
import type {
  AdminIntegration,
  AdminIntegrationDetail,
  IntegrationAction,
} from "@/lib/integrations/types";

export function makeIntegration(
  overrides: Partial<AdminIntegration> = {}
): AdminIntegration {
  return {
    id: 1,
    kind: "mcp",
    shape: "mcp_server",
    name: "Linear",
    description: "Manage issues",
    preset_id: null,
    enabled: true,
    auth_mode: "individual",
    auth_method: "oauth2",
    installation_policy: "AVAILABLE",
    access: makeAccess({ can_manage: true }),
    created_by_email: "admin@example.com",
    action_count: 3,
    needs_setup: false,
    setup_reason: null,
    organization_status: null,
    can_manage: true,
    ...overrides,
  };
}

export function makeDetail(
  overrides: Partial<AdminIntegrationDetail> = {}
): AdminIntegrationDetail {
  return {
    ...makeIntegration(),
    config: {
      shape: "mcp_server",
      server_url: "https://mcp.linear.app/mcp",
      transport: "STREAMABLE_HTTP",
    },
    credential_fields: [],
    header_template: null,
    users_can_save_always_allow: true,
    oauth_client: {
      provider_mode: "manual",
      authorization_url: "https://linear.app/oauth/authorize",
      token_url: "https://api.linear.app/oauth/token",
      scopes: ["read"],
      additional_params: null,
      pkce: null,
      client_id: "client-1",
      has_client_secret: true,
    },
    can_delete: true,
    group_settings: [],
    group_shares: [],
    ...overrides,
  };
}

export function makeAction(
  overrides: Partial<IntegrationAction> = {}
): IntegrationAction {
  return {
    key: "list_issues",
    display_name: "List issues",
    description: "Read the issues",
    read_only: true,
    default_policy: "allow",
    admin_policy: null,
    effective_admin_policy: "allow",
    always_asks: false,
    ...overrides,
  };
}

/** A fetch mock that answers JSON by `METHOD url` or `url`, and records calls. */
export function mockFetch(
  routes: Record<string, unknown | ((init?: RequestInit) => unknown)>
) {
  return jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const key = `${method} ${url}` in routes ? `${method} ${url}` : url;
    if (!(key in routes))
      throw new Error(`Unexpected request: ${method} ${url}`);
    const route = routes[key];
    const body = typeof route === "function" ? await route(init) : route;
    if (body instanceof Response) return body;
    return new Response(body === null ? null : JSON.stringify(body), {
      status: body === null ? 204 : 200,
    });
  });
}

/** The parsed JSON body of the fetch call to `METHOD url`. */
export function requestBody(
  fetchMock: jest.SpyInstance,
  method: string,
  url: string
): unknown {
  const call = fetchMock.mock.calls.find(
    ([input, init]) =>
      String(input) === url && (init?.method ?? "GET") === method
  );
  if (!call) throw new Error(`No ${method} ${url} request`);
  const init: RequestInit | undefined = call[1];
  return typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
}
