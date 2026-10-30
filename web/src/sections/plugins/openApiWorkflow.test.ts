import { saveOpenApiAuthentication } from "@/sections/plugins/openApiWorkflow";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { OpenAPIAuthFormValues } from "@/sections/actions/modals/OpenAPIAuthenticationModal";

const tool: ToolSnapshot = {
  id: 42,
  name: "Release API",
  display_name: "Release API",
  description: "Read releases",
  definition: null,
  custom_headers: [{ key: "Authorization", value: "********" }],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  oauth_config_id: 7,
};
const values: OpenAPIAuthFormValues = {
  authMethod: "oauth",
  authorizationUrl: "https://identity.example.com/authorize",
  tokenUrl: "https://identity.example.com/token",
  clientId: "client-id",
  clientSecret: "client-secret",
  scopes: "read, write",
  supportsPkce: true,
  headers: [{ key: " Authorization ", value: " ******** " }],
};

let writes: { path: string; body: unknown }[];
beforeEach(() => {
  writes = [];
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    writes.push({ path: String(input), body: JSON.parse(String(init?.body)) });
    return new Response(JSON.stringify({ id: 9 }));
  });
});
afterEach(() => jest.restoreAllMocks());

test("switching to headers clears OAuth and pass-through while retaining masked header values", async () => {
  await saveOpenApiAuthentication({
    tool,
    values: { ...values, authMethod: "custom-header" },
  });
  expect(writes).toEqual([
    {
      path: "/api/admin/tool/custom/42",
      body: {
        custom_headers: [{ key: "Authorization", value: "********" }],
        passthrough_auth: false,
        oauth_config_id: null,
      },
    },
  ]);
});

test("switching to pass-through clears custom headers and OAuth", async () => {
  await saveOpenApiAuthentication({
    tool,
    values: { ...values, authMethod: "pt-oauth" },
  });
  expect(writes).toEqual([
    {
      path: "/api/admin/tool/custom/42",
      body: {
        custom_headers: [],
        passthrough_auth: true,
        oauth_config_id: null,
      },
    },
  ]);
});

test("switching to OAuth creates and attaches its configuration while clearing incompatible methods", async () => {
  await saveOpenApiAuthentication({
    tool: { ...tool, oauth_config_id: null },
    values,
  });
  expect(writes).toEqual([
    {
      path: "/api/admin/oauth-config/create",
      body: {
        name: "Release API OAuth",
        authorization_url: "https://identity.example.com/authorize",
        token_url: "https://identity.example.com/token",
        client_id: "client-id",
        client_secret: "client-secret",
        scopes: ["read", "write"],
        supports_pkce: true,
      },
    },
    {
      path: "/api/admin/tool/custom/42",
      body: { custom_headers: [], passthrough_auth: false, oauth_config_id: 9 },
    },
  ]);
});

test("updating existing OAuth omits unchanged credentials", async () => {
  await saveOpenApiAuthentication({
    tool,
    values: { ...values, clientId: "", clientSecret: "" },
    pendingOAuthConfigId: 99,
  });
  expect(writes).toEqual([
    {
      path: "/api/admin/oauth-config/7",
      body: {
        authorization_url: "https://identity.example.com/authorize",
        token_url: "https://identity.example.com/token",
        scopes: ["read", "write"],
        supports_pkce: true,
      },
    },
    {
      path: "/api/admin/tool/custom/42",
      body: { custom_headers: [], passthrough_auth: false, oauth_config_id: 7 },
    },
  ]);
});

test("does not create an OAuth configuration from masked credentials after its previous configuration is removed", async () => {
  await expect(
    saveOpenApiAuthentication({
      tool: { ...tool, oauth_config_id: null },
      values: { ...values, clientId: "********", clientSecret: "********" },
    })
  ).rejects.toThrow();
  expect(writes).toEqual([]);
});

test("retains a newly created OAuth ID when linking fails so retry updates the same configuration", async () => {
  let configId: number | null = null;
  let configCreates = 0;
  let linkAttempts = 0;
  jest.mocked(global.fetch).mockImplementation(async (input, init) => {
    const path = String(input);
    writes.push({ path, body: JSON.parse(String(init?.body)) });
    if (path === "/api/admin/oauth-config/create") {
      configCreates += 1;
      return new Response(JSON.stringify({ id: 9 }));
    }
    if (path === "/api/admin/tool/custom/42" && linkAttempts++ === 0)
      return new Response(JSON.stringify({ detail: "Link failed" }), {
        status: 503,
      });
    return new Response(JSON.stringify({ id: 9 }));
  });
  await expect(
    saveOpenApiAuthentication({
      tool: { ...tool, oauth_config_id: null },
      values,
      onOAuthConfigCreated: (id) => {
        configId = id;
      },
    })
  ).rejects.toThrow();
  expect(configId).toBe(9);
  await saveOpenApiAuthentication({
    tool: { ...tool, oauth_config_id: null },
    values,
    pendingOAuthConfigId: configId,
  });
  expect(configCreates).toBe(1);
  expect(writes).toContainEqual({
    path: "/api/admin/oauth-config/9",
    body: {
      authorization_url: "https://identity.example.com/authorize",
      token_url: "https://identity.example.com/token",
      scopes: ["read", "write"],
      supports_pkce: true,
      client_id: "client-id",
      client_secret: "client-secret",
    },
  });
});
