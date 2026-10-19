jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => ({ push: jest.fn() }),
}));

import { useState } from "react";
import useSWR from "swr";
import { Button, Modal } from "@opal/components";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MCPAuthenticationPage from "@/sections/actions/modals/MCPAuthenticationPage";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPOAuthProviderMode,
  MCPServer,
  MCPServerStatus,
  MCPTransportType,
} from "@/lib/mcp/types";
import type { MCPOAuthDiscovery } from "@/lib/mcp/types";
import type { MCPOAuthFailureReason } from "@/lib/mcp/svc";
import messages from "@/i18n/messages/en.json";

const copy = messages.actions.mcpAuthModal;
const server: MCPServer = {
  connection_status: null,
  id: 7,
  name: "Example MCP",
  server_url: "https://example.com/mcp",
  owner: "admin@example.com",
  transport: MCPTransportType.SSE,
  auth_type: MCPAuthenticationType.OAUTH,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
  oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
  admin_credentials: { client_id: "registered-client" },
  status: MCPServerStatus.CREATED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 0,
};

function LoadedAuthentication({
  serverId,
  fetchTools,
  onComplete,
  onBusyChange,
}: {
  serverId: number;
  fetchTools: (serverId: number) => Promise<void>;
  onComplete: () => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const { data, isValidating } = useSWR<MCPServer>(
    SWR_KEYS.adminMcpServer(serverId),
    errorHandlingFetcher,
    { revalidateOnMount: true, revalidateOnFocus: false, dedupingInterval: 0 }
  );
  return data && !isValidating ? (
    <MCPAuthenticationPage
      active
      variant="page"
      mcpServer={data}
      onTriggerFetchTools={fetchTools}
      onBusyChange={onBusyChange}
      onSaved={async () => {}}
      onComplete={onComplete}
    />
  ) : null;
}

function Harness({
  configuredServer,
  fetchTools,
}: {
  configuredServer: MCPServer;
  fetchTools: (serverId: number) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const close = () => {
    if (!busy) setOpen(false);
  };
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open setup</Button>
      <Modal
        open={open}
        onOpenChange={(next) => {
          if (!next) close();
        }}
      >
        <Modal.Content preventAccidentalClose={false}>
          <Modal.Header title="Authentication" onClose={close} />
          <Modal.Body>
            {open && (
              <LoadedAuthentication
                serverId={configuredServer.id}
                fetchTools={fetchTools}
                onComplete={() => setOpen(false)}
                onBusyChange={setBusy}
              />
            )}
          </Modal.Body>
        </Modal.Content>
      </Modal>
    </>
  );
}

function mockNetwork(
  configuredServer: MCPServer,
  oauthError?: string,
  oauthEnabled = false,
  options: {
    discovery?: MCPOAuthDiscovery;
    oauthReason?: MCPOAuthFailureReason;
  } = {}
) {
  return jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/admin/mcp/server/7/tools/snapshots") {
      return new Response("[]");
    }
    if (url === "/api/admin/mcp/servers/7") {
      return new Response(JSON.stringify(configuredServer));
    }
    if (url === "/api/settings") {
      return new Response(JSON.stringify({ ee_features_enabled: false }));
    }
    if (url === "/api/auth/type") {
      return new Response(
        JSON.stringify({ auth_type: "basic", oauth_enabled: oauthEnabled })
      );
    }
    if (url === "/api/admin/mcp/oauth/discover") {
      return new Response(
        JSON.stringify(
          options.discovery ?? {
            status: "metadata_found",
            supports_automatic_registration: true,
            authorization_endpoint: "https://identity.example.com/authorize",
            token_endpoint: "https://identity.example.com/token",
          }
        )
      );
    }
    if (url === "/api/admin/mcp/servers/create") {
      return new Response(JSON.stringify({ server_id: configuredServer.id }));
    }
    if (url.startsWith("/api/admin/mcp/server/7/status?")) {
      return new Response("{}");
    }
    if (url === "/api/admin/mcp/oauth/connect") {
      return oauthError
        ? new Response(
            JSON.stringify({
              detail: oauthError,
              oauth_error: options.oauthReason,
            }),
            { status: 400 }
          )
        : new Response(
            JSON.stringify({
              status: "already_authenticated",
              server_id: configuredServer.id,
              authorization_url: null,
              redirect_url: "/admin/mcp-actions/?trigger_fetch=true",
            })
          );
    }
    throw new Error(`Unexpected request: ${url}`);
  });
}

async function expandSection(
  user: ReturnType<typeof setupUser>,
  title: string
) {
  await screen.findByRole("button", {
    name: new RegExp(`^(Expand|Fold) ${title}$`),
  });
  const expand = screen.queryByRole("button", {
    name: `Expand ${title}`,
  });
  if (expand) await user.click(expand);
  expect(screen.getByRole("button", { name: `Fold ${title}` })).toBeVisible();
}

async function openSetup(
  configuredServer = server,
  fetchTools = jest.fn().mockResolvedValue(undefined),
  user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never })
) {
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByDisplayValue("registered-client");
  return user;
}

afterEach(() => jest.restoreAllMocks());

test("blocks a shared-token template that no longer sends the shared key", async () => {
  const configuredServer: MCPServer = {
    ...server,
    auth_type: MCPAuthenticationType.API_TOKEN,
    auth_performer: MCPAuthenticationPerformer.ADMIN,
    admin_credentials: { api_key: "********" },
    auth_template: {
      headers: { "X-API-Key": "{api_key}" },
      required_fields: ["api_key"],
    },
  };
  const network = mockNetwork(configuredServer);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={jest.fn()} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await expandSection(user, "Advanced settings");
  const headerValue = screen.getByDisplayValue("{api_key}");
  await user.clear(headerValue);
  await user.type(headerValue, "constant-value");
  await waitFor(() =>
    expect(screen.getByTestId("mcp-auth-connect-button")).toBeDisabled()
  );
  expect(
    screen.getByText(
      "At least one header value must include the {api_key} placeholder."
    )
  ).toBeVisible();
  expect(
    network.mock.calls.some(([url]) => url === "/api/admin/mcp/servers/create")
  ).toBe(false);
});

test("clears OAuth failure actions when choosing another authentication method", async () => {
  mockNetwork(server, "Registration failed", false, {
    oauthReason: "client_registration_failed",
  });
  const user = await openSetup();
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    copy.errors.clientRegistrationFailed
  );
  await user.click(screen.getByRole("combobox", { name: copy.authType.label }));
  await user.click(
    screen.getByRole("option", { name: copy.authType.none.label })
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: copy.discovery.useOwnClient })
  ).not.toBeInTheDocument();
});

test("preserves a saved SSE transport and discovers tools once when OAuth is already connected", async () => {
  const fetchSpy = mockNetwork(server);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = await openSetup(server, fetchTools);
  const originalLocation = window.location.href;

  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );

  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  expect(fetchTools).toHaveBeenCalledWith(7);
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/admin/mcp/servers/create",
    expect.objectContaining({
      body: expect.stringContaining('"transport":"SSE"'),
    })
  );
  expect(window.location.href).toBe(originalLocation);
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

test("keeps edited client credentials visible after OAuth startup fails", async () => {
  mockNetwork(server, "Protected resource metadata was not found");
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = await openSetup(server, fetchTools);
  const clientId = screen.getByLabelText(copy.clientId.label, { exact: false });
  await user.clear(clientId);
  await user.type(clientId, "replacement-client");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Protected resource metadata was not found"
  );
  expect(
    screen.getByLabelText(copy.clientId.label, { exact: false })
  ).toHaveValue("replacement-client");
  expect(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  ).toBeEnabled();
  expect(fetchTools).not.toHaveBeenCalled();
});

test("keeps setup open when asynchronous tool discovery fails", async () => {
  mockNetwork(server);
  const fetchTools = jest
    .fn()
    .mockRejectedValue(new Error("Tool listing timed out"));
  const user = await openSetup(server, fetchTools);
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Tool listing timed out"
  );
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(
    screen.getByLabelText(copy.clientId.label, { exact: false })
  ).toHaveValue("registered-client");
});

test("retains manual OAuth settings and required custom header values", async () => {
  const configuredServer: MCPServer = {
    ...server,
    oauth_provider_mode: MCPOAuthProviderMode.KNOWN_PROVIDER,
    oauth_authorization_endpoint: "https://identity.example.com/authorize",
    oauth_token_endpoint: "https://identity.example.com/token",
    oauth_scopes_override: ["read", "write"],
    auth_template: {
      headers: { "X-Workspace": "{workspace}" },
      required_fields: ["workspace"],
    },
    user_credentials: { workspace: "engineering" },
  };
  const fetchSpy = mockNetwork(configuredServer);
  const user = await openSetup(configuredServer);
  expect(screen.getByLabelText("Workspace")).toHaveValue("engineering");
  expect(screen.getByLabelText(copy.authorizationEndpoint.label)).toHaveValue(
    configuredServer.oauth_authorization_endpoint
  );
  await user.clear(screen.getByLabelText("Workspace"));
  await user.type(screen.getByLabelText("Workspace"), "support");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );

  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/mcp/servers/create",
      expect.objectContaining({
        body: expect.stringContaining('"workspace":"support"'),
      })
    )
  );
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
    expect.objectContaining({
      oauth_provider_mode: MCPOAuthProviderMode.KNOWN_PROVIDER,
      oauth_client_id: "registered-client",
      oauth_client_id_changed: false,
      oauth_scopes_override: ["read", "write"],
      auth_template: configuredServer.auth_template,
      admin_credentials_changed: { workspace: true },
    })
  );
});

test("compares retry edits with the configuration saved before OAuth failed", async () => {
  const fetchSpy = mockNetwork(server, "Provider is unavailable");
  const user = await openSetup();
  const clientId = screen.getByLabelText(copy.clientId.label, { exact: false });
  await user.clear(clientId);
  await user.type(clientId, "replacement-client");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Provider is unavailable"
  );

  await user.clear(clientId);
  await user.type(clientId, "registered-client");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() =>
    expect(
      fetchSpy.mock.calls.filter(
        ([url]) => url === "/api/admin/mcp/servers/create"
      )
    ).toHaveLength(2)
  );
  const submissions = fetchSpy.mock.calls.filter(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submissions[1]?.[1]?.body))).toEqual(
    expect.objectContaining({
      oauth_client_id: "registered-client",
      oauth_client_id_changed: true,
    })
  );
});

test("loads current server settings when setup is reopened", async () => {
  const configuredServer = { ...server };
  const fetchSpy = mockNetwork(configuredServer);
  const user = await openSetup(configuredServer);
  await user.click(screen.getByRole("button", { name: "Close" }));
  configuredServer.admin_credentials = { client_id: "newly-registered-client" };
  await user.click(screen.getByRole("button", { name: "Open setup" }));

  await waitFor(() =>
    expect(
      fetchSpy.mock.calls.filter(([url]) => url === "/api/admin/mcp/servers/7")
    ).toHaveLength(2)
  );
  expect(
    await screen.findByDisplayValue("newly-registered-client")
  ).toBeInTheDocument();
  expect(
    screen.queryByDisplayValue("registered-client")
  ).not.toBeInTheDocument();
});

test("removes the default bearer token prompt when switching to OAuth", async () => {
  const configuredServer: MCPServer = {
    ...server,
    auth_type: MCPAuthenticationType.API_TOKEN,
    admin_credentials: {},
    auth_template: { headers: {}, required_fields: [] },
  };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  expect(
    await screen.findByLabelText("API Key", { selector: "input" })
  ).toBeInTheDocument();
  await user.click(screen.getByRole("combobox", { name: copy.authType.label }));
  await user.click(
    screen.getByRole("option", { name: copy.authType.oauth.label })
  );
  expect(
    screen.queryByLabelText("API Key", { selector: "input" })
  ).not.toBeInTheDocument();
  await screen.findByRole("radio", { name: copy.oauthSetup.automatic.label });
  await waitFor(() =>
    expect(
      screen.getByRole("button", {
        name: copy.submitButton.label,
      })
    ).toBeEnabled()
  );
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
    expect.objectContaining({
      auth_type: MCPAuthenticationType.OAUTH,
      auth_template: { headers: {}, required_fields: [] },
    })
  );
});

test("preserves a masked shared token while editing its custom header name", async () => {
  const configuredServer: MCPServer = {
    ...server,
    auth_type: MCPAuthenticationType.API_TOKEN,
    auth_performer: MCPAuthenticationPerformer.ADMIN,
    admin_credentials: { api_key: "********" },
    auth_template: {
      headers: { "X-API-Key": "{api_key}" },
      required_fields: ["api_key"],
    },
  };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  // The stored token shows as a tag; the input itself stays empty.
  expect(
    await screen.findByLabelText(copy.sharedApiKey.label, { selector: "input" })
  ).toHaveValue("");
  expect(screen.getByText("********")).toBeInTheDocument();
  expect(
    screen.getAllByLabelText("API Key", { selector: "input" })
  ).toHaveLength(1);
  await expandSection(user, "Advanced settings");
  const headerName = screen.getByDisplayValue("X-API-Key");
  await user.clear(headerName);
  await user.type(headerName, "X-Service-Key");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
    expect.objectContaining({
      auth_performer: MCPAuthenticationPerformer.ADMIN,
      api_token: "********",
      api_token_changed: false,
      auth_template: {
        headers: { "X-Service-Key": "{api_key}" },
        required_fields: ["api_key"],
      },
      auth_template_headers_changed: { "X-Service-Key": true },
    })
  );
});

test("keeps personal credentials visible and shows headers directly in advanced settings", async () => {
  const configuredServer: MCPServer = {
    ...server,
    auth_type: MCPAuthenticationType.API_TOKEN,
    admin_credentials: {},
    user_credentials: {},
    auth_template: {
      headers: {
        "X-Service-Token": "{api_key}",
        "X-Workspace": "{workspace}",
        "X-User": "{user_email}",
      },
      required_fields: ["api_key", "workspace"],
    },
  };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  const token = await screen.findByLabelText("API Key", { selector: "input" });
  const workspace = screen.getByLabelText("Workspace");
  expect(token).toBeVisible();
  expect(workspace).toBeVisible();
  expect(screen.queryByLabelText("User Email")).not.toBeInTheDocument();
  await expandSection(user, "Advanced settings");
  expect(screen.getByDisplayValue("X-Workspace")).toBeVisible();
  await user.type(token, "personal-token");
  await user.type(workspace, "support");
  const headerName = screen.getByDisplayValue("X-Workspace");
  await user.clear(headerName);
  await user.type(headerName, "X-Team");
  expect(screen.getByLabelText("Workspace")).toHaveValue("support");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
    expect.objectContaining({
      auth_performer: MCPAuthenticationPerformer.PER_USER,
      admin_credentials: { api_key: "personal-token", workspace: "support" },
      admin_credentials_changed: { api_key: true, workspace: true },
      auth_template: {
        headers: {
          "X-Service-Token": "{api_key}",
          "X-Team": "{workspace}",
          "X-User": "{user_email}",
        },
        required_fields: ["api_key", "workspace"],
      },
    })
  );
});

test("requires new credentials when switching between shared and personal token scopes", async () => {
  const configuredServer: MCPServer = {
    ...server,
    auth_type: MCPAuthenticationType.API_TOKEN,
    auth_performer: MCPAuthenticationPerformer.ADMIN,
    admin_credentials: { api_key: "********", workspace: "shared-workspace" },
    auth_template: {
      headers: { "X-Key": "{api_key}", "X-Workspace": "{workspace}" },
      required_fields: ["api_key", "workspace"],
    },
  };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  // The stored token shows as a tag; the input itself stays empty.
  expect(
    await screen.findByLabelText(copy.sharedApiKey.label, { selector: "input" })
  ).toHaveValue("");
  expect(screen.getByText("********")).toBeInTheDocument();
  await user.click(screen.getByRole("combobox", { name: "Credentials" }));
  await user.click(
    screen.getByRole("option", { name: copy.apiKeyTabs.perUser.label })
  );
  expect(screen.getByLabelText("API Key", { selector: "input" })).toHaveValue(
    ""
  );
  expect(screen.getByLabelText("Workspace")).toHaveValue("");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  expect(fetchTools).not.toHaveBeenCalled();
  expect(
    fetchSpy.mock.calls.filter(
      ([url]) => url === "/api/admin/mcp/servers/create"
    )
  ).toHaveLength(0);

  await user.type(
    screen.getByLabelText("API Key", { selector: "input" }),
    "personal-token"
  );
  await user.type(screen.getByLabelText("Workspace"), "personal-workspace");
  await user.click(screen.getByRole("combobox", { name: "Credentials" }));
  await user.click(
    screen.getByRole("option", { name: copy.apiKeyTabs.admin.label })
  );
  expect(
    screen.getByLabelText(copy.sharedApiKey.label, { selector: "input" })
  ).toHaveValue("");
  expect(screen.getByLabelText("Workspace")).toHaveValue("");
  await user.type(
    screen.getByLabelText(copy.sharedApiKey.label, { selector: "input" }),
    "service-token"
  );
  await user.type(screen.getByLabelText("Workspace"), "service-workspace");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
    expect.objectContaining({
      api_token: "service-token",
      api_token_changed: true,
      admin_credentials: { workspace: "service-workspace" },
      auth_template: configuredServer.auth_template,
    })
  );
});

test("keeps setup open while connection work is pending", async () => {
  mockNetwork(server);
  const discovery = deferred<void>();
  const fetchTools = jest.fn(() => discovery.promise);
  const user = await openSetup(server, fetchTools);
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  expect(screen.getByTestId("mcp-auth-connect-button")).toBeDisabled();
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () => discovery.resolve());
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

test("shows OAuth fields without opening advanced settings and preserves masked credentials", async () => {
  const configuredServer = {
    ...server,
    admin_credentials: {
      client_id: "registered-client",
      client_secret: "********",
    },
  };
  const fetchSpy = mockNetwork(configuredServer);
  const user = await openSetup(configuredServer);
  expect(
    screen.getByLabelText(copy.clientId.label, { exact: false })
  ).toBeVisible();
  // The stored secret shows as a tag; the input itself stays empty.
  expect(
    screen.getByLabelText(copy.clientSecret.label, { exact: false })
  ).toHaveValue("");
  expect(screen.getByText("********")).toBeInTheDocument();
  expect(
    screen.getByRole("combobox", { name: copy.providerMode.placeholder })
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Expand Advanced settings" })
  ).toHaveAttribute("aria-expanded", "false");
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
    expect.objectContaining({
      oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
      oauth_client_id: "registered-client",
      oauth_client_secret: "********",
      oauth_client_id_changed: false,
      oauth_client_secret_changed: false,
    })
  );
});

test("manual OAuth requires a client ID before saving or starting authorization", async () => {
  const configuredServer: MCPServer = {
    ...server,
    admin_credentials: {},
    oauth_provider_mode: MCPOAuthProviderMode.KNOWN_PROVIDER,
    oauth_authorization_endpoint: "https://identity.example.com/authorize",
    oauth_token_endpoint: "https://identity.example.com/token",
  };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  expect(
    await screen.findByLabelText(copy.clientId.label, { exact: false })
  ).toBeVisible();
  expect(screen.getByLabelText(copy.authorizationEndpoint.label)).toBeVisible();
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  expect(await screen.findByText(copy.clientId.required)).toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(
      ([url]) =>
        url === "/api/admin/mcp/servers/create" ||
        url === "/api/admin/mcp/oauth/connect"
    )
  ).toBe(false);
  expect(fetchTools).not.toHaveBeenCalled();
});

test("each authentication method shows its explanation in the main form", async () => {
  mockNetwork(server, undefined, true);
  const user = await openSetup();
  expect(
    screen.getByRole("combobox", { name: copy.authType.label })
  ).toHaveValue(copy.authType.oauth.label);
  expect(
    screen.getByText(copy.oauthInfo.discovery.replaceAll("{appName}", "Onyx"))
  ).toBeVisible();
  await user.click(screen.getByRole("combobox", { name: copy.authType.label }));
  await user.click(
    screen.getByRole("option", { name: copy.authType.apiToken.label })
  );
  expect(screen.getByText(copy.apiTokenInfo.description)).toBeVisible();
  await user.click(screen.getByRole("combobox", { name: copy.authType.label }));
  await user.click(
    screen.getByRole("option", { name: copy.authType.none.label })
  );
  expect(screen.getByText(copy.noAuthNotice.description)).toBeVisible();
  await user.click(screen.getByRole("combobox", { name: copy.authType.label }));
  await user.click(
    screen.getByRole("option", { name: copy.authType.ptOauth.label })
  );
  expect(
    screen.getByText(
      copy.passThroughNotice.description.replaceAll("{appName}", "Onyx")
    )
  ).toBeVisible();
});

test("OAuth setup choices support keyboard navigation", async () => {
  mockNetwork(server);
  const user = await openSetup(server);
  const automatic = await screen.findByRole("radio", {
    name: copy.oauthSetup.automatic.label,
  });
  await user.click(automatic);
  await user.keyboard("{ArrowDown}");
  const ownClient = screen.getByRole("radio", {
    name: copy.oauthSetup.ownClient.label,
  });
  expect(ownClient).toHaveFocus();
  expect(ownClient).toHaveAttribute("aria-checked", "true");
  expect(
    screen.getByLabelText(copy.clientId.label, { exact: false })
  ).toBeVisible();
  await user.keyboard("{Home}");
  expect(automatic).toHaveFocus();
  expect(automatic).toHaveAttribute("aria-checked", "true");
});

test("new OAuth setup starts automatically and own-client setup requires a client ID", async () => {
  const configuredServer = { ...server, admin_credentials: {} };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = setupUser();
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByRole("radiogroup", { name: copy.oauthSetup.label });
  expect(
    screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
  ).toHaveAttribute("aria-checked", "true");
  expect(
    screen.queryByLabelText(copy.clientId.label, { exact: false })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("combobox", { name: copy.providerMode.placeholder })
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("radio", {
      name: new RegExp(`^${copy.oauthSetup.ownClient.label}`),
    })
  );
  expect(
    screen.getByLabelText(copy.clientId.label, { exact: false })
  ).toBeVisible();
  expect(
    screen.getByRole("combobox", { name: copy.providerMode.placeholder })
  ).toHaveValue(copy.providerMode.autoDiscovery.label);
  expect(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  ).toBeDisabled();
  expect(
    fetchSpy.mock.calls.some(([url]) => url === "/api/admin/mcp/servers/create")
  ).toBe(false);
  await user.type(
    screen.getByLabelText(copy.clientId.label, { exact: false }),
    "provider-client"
  );
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
});

test("automatic setup can turn off the client metadata document", async () => {
  const configuredServer = { ...server, admin_credentials: {} };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = setupUser();
  render(
    <Harness configuredServer={configuredServer} fetchTools={fetchTools} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByRole("radiogroup", { name: copy.oauthSetup.label });
  const cimdSwitch = screen.getByRole("switch", {
    name: new RegExp(`^${copy.cimd.label}`),
  });
  expect(cimdSwitch).toBeChecked();
  await user.click(cimdSwitch);
  expect(cimdSwitch).not.toBeChecked();
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
    expect.objectContaining({
      oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
      oauth_cimd_enabled: false,
    })
  );
});

test("switching an existing client to automatic setup clears its credentials and manual endpoints", async () => {
  const configuredServer: MCPServer = {
    ...server,
    admin_credentials: {
      client_id: "registered-client",
      client_secret: "********",
    },
    oauth_provider_mode: MCPOAuthProviderMode.KNOWN_PROVIDER,
    oauth_authorization_endpoint: "https://identity.example.com/authorize",
    oauth_token_endpoint: "https://identity.example.com/token",
    oauth_scopes_override: ["read"],
    oauth_additional_auth_params: { prompt: "consent" },
  };
  const fetchSpy = mockNetwork(configuredServer);
  const fetchTools = jest.fn().mockResolvedValue(undefined);
  const user = await openSetup(
    configuredServer,
    fetchTools,
    setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never })
  );
  expect(
    screen.getByRole("radio", { name: copy.oauthSetup.ownClient.label })
  ).toHaveAttribute("aria-checked", "true");
  await user.click(
    screen.getByRole("radio", {
      name: new RegExp(`^${copy.oauthSetup.automatic.label}`),
    })
  );
  expect(
    screen.queryByLabelText(copy.clientId.label, { exact: false })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText(copy.authorizationEndpoint.label)
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(fetchTools).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/servers/create"
  );
  const payload = JSON.parse(String(submission?.[1]?.body));
  expect(payload).toEqual(
    expect.objectContaining({
      oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
      oauth_client_id: "",
      oauth_client_secret: "",
      oauth_client_id_changed: true,
      oauth_client_secret_changed: true,
    })
  );
  expect(payload).not.toHaveProperty("oauth_authorization_endpoint");
  expect(payload).not.toHaveProperty("oauth_token_endpoint");
  expect(payload).not.toHaveProperty("oauth_scopes_override");
  expect(payload).not.toHaveProperty("oauth_additional_auth_params");
  const oauth = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/oauth/connect"
  );
  expect(JSON.parse(String(oauth?.[1]?.body))).toEqual(
    expect.objectContaining({
      oauth_client_id: "",
      oauth_client_secret: "",
      oauth_client_id_changed: true,
      oauth_client_secret_changed: true,
    })
  );
});

test.each(["registered-client", ""])(
  "discovery recommends own-client setup but allows automatic setup with saved ID %s",
  async (clientId) => {
    const configuredServer = {
      ...server,
      admin_credentials: { client_id: clientId },
    };
    mockNetwork(configuredServer, undefined, false, {
      discovery: {
        status: "metadata_found",
        supports_automatic_registration: false,
        authorization_endpoint: "https://identity.example.com/authorize",
        token_endpoint: "https://identity.example.com/token",
      },
    });
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    render(
      <Harness configuredServer={configuredServer} fetchTools={jest.fn()} />
    );
    await user.click(screen.getByRole("button", { name: "Open setup" }));
    await screen.findByLabelText(copy.clientId.label, { exact: false });
    expect(
      screen.queryByText(copy.discovery.requiresClient)
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
    ).toBeEnabled();
    expect(
      screen.getByRole("radio", { name: copy.oauthSetup.ownClient.label })
    ).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByLabelText(copy.clientId.label, { exact: false })
    ).toHaveValue(clientId);
    await user.click(
      screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
    );
    expect(
      screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
    ).toHaveAttribute("aria-checked", "true");
    expect(
      await screen.findByText(copy.discovery.requiresClient)
    ).toBeVisible();
    await waitFor(() =>
      expect(screen.getByTestId("mcp-auth-connect-button")).toBeEnabled()
    );
  }
);

test("missing metadata offers manual endpoints and retains the existing client", async () => {
  mockNetwork(server, undefined, false, {
    discovery: {
      status: "metadata_missing",
      supports_automatic_registration: null,
      authorization_endpoint: null,
      token_endpoint: null,
    },
  });
  const user = await openSetup(
    server,
    undefined,
    setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never })
  );
  expect(screen.queryByText(copy.discovery.missing)).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("combobox", { name: copy.providerMode.placeholder })
  );
  await user.click(
    screen.getByRole("option", {
      name: new RegExp(`^${copy.providerMode.knownProvider.label}`),
    })
  );
  expect(screen.getByLabelText(copy.authorizationEndpoint.label)).toBeVisible();
  expect(screen.getByLabelText(copy.tokenEndpoint.label)).toBeVisible();
  expect(
    screen.getByLabelText(copy.clientId.label, { exact: false })
  ).toHaveValue("registered-client");
});

test("registration failures show a clear recovery action instead of provider HTML", async () => {
  const configuredServer: MCPServer = {
    ...server,
    admin_credentials: {},
  };
  mockNetwork(configuredServer, "<html>Provider internal error</html>", false, {
    oauthReason: "client_registration_failed",
  });
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={jest.fn()} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByRole("radio", { name: copy.oauthSetup.automatic.label });
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  const recovery = await screen.findByRole("button", {
    name: copy.discovery.useOwnClient,
  });
  expect(screen.getByRole("alert")).not.toHaveTextContent("<html>");
  expect(screen.getByRole("alert")).not.toHaveTextContent(
    "Provider internal error"
  );
  await user.click(recovery);
  expect(
    screen.getByRole("radio", { name: copy.oauthSetup.ownClient.label })
  ).toHaveAttribute("aria-checked", "true");
  expect(
    screen.getByLabelText(copy.clientId.label, { exact: false })
  ).toBeVisible();
});

test("retrying unavailable discovery refreshes support while preserving automatic setup", async () => {
  const options: { discovery: MCPOAuthDiscovery } = {
    discovery: {
      status: "unreachable",
      supports_automatic_registration: null,
      authorization_endpoint: null,
      token_endpoint: null,
    },
  };
  const configuredServer = { ...server, admin_credentials: {} };
  const fetchSpy = mockNetwork(configuredServer, undefined, false, options);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} fetchTools={jest.fn()} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByText(copy.discovery.unreachable);
  options.discovery = {
    ...options.discovery,
    status: "metadata_found",
    supports_automatic_registration: true,
  };
  await user.click(screen.getByRole("button", { name: copy.discovery.retry }));
  expect(
    await screen.findByRole("radio", { name: copy.oauthSetup.automatic.label })
  ).toBeVisible();
  expect(
    screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
  ).toHaveAttribute("aria-checked", "true");
  expect(
    fetchSpy.mock.calls.filter(
      ([url]) => url === "/api/admin/mcp/oauth/discover"
    )
  ).toHaveLength(2);
});

test("preserves freshly loaded server metadata when saving authentication", async () => {
  const freshServer: MCPServer = {
    ...server,
    name: "Renamed MCP",
    description: "Updated description",
    server_url: "https://updated.example.com/mcp",
  };
  const network = mockNetwork(freshServer);
  const user = await openSetup(server);
  await user.click(screen.getByTestId("mcp-auth-connect-button"));
  await waitFor(() => {
    const request = network.mock.calls.find(
      ([url]) => String(url) === "/api/admin/mcp/servers/create"
    );
    expect(request).toBeDefined();
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      name: freshServer.name,
      description: freshServer.description,
      server_url: freshServer.server_url,
    });
  });
});

test("keeps an explicit automatic choice when discovery finishes late", async () => {
  const network = mockNetwork(server);
  const original = network.getMockImplementation()!;
  const discovery = deferred<Response>();
  network.mockImplementation((input, init) =>
    String(input) === "/api/admin/mcp/oauth/discover"
      ? discovery.promise
      : original(input, init)
  );
  const user = await openSetup(server);
  await user.click(
    screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
  );
  await act(async () =>
    discovery.resolve(
      new Response(
        JSON.stringify({
          status: "metadata_found",
          supports_automatic_registration: false,
          authorization_endpoint: "https://example.com/authorize",
          token_endpoint: "https://example.com/token",
        })
      )
    )
  );
  expect(await screen.findByText(copy.discovery.requiresClient)).toBeVisible();
  expect(
    screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
  ).toHaveAttribute("aria-checked", "true");
});

describe("inline authentication", () => {
  test("saved authentication stays clean until an actual field changes", async () => {
    const configuredServer = { ...server, status: MCPServerStatus.CONNECTED };
    mockNetwork(configuredServer);
    const dirty = jest.fn();
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        mcpServer={configuredServer}
        onTriggerFetchTools={async () => {}}
        onBusyChange={() => {}}
        onDirtyChange={dirty}
        onSaved={async () => {}}
        onComplete={() => {}}
      />
    );
    const save = screen.getByTestId("mcp-auth-connect-button");
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
    expect(save).toBeDisabled();
    const user = setupUser();
    const clientId = screen.getByLabelText(copy.clientId.label, {
      exact: false,
    });
    await user.clear(clientId);
    await user.type(clientId, "updated-client");
    await waitFor(() => expect(save).toBeEnabled());
    expect(dirty).toHaveBeenLastCalledWith(true);
    await user.clear(clientId);
    await user.type(clientId, "registered-client");
    await waitFor(() => expect(save).toBeDisabled());
    expect(dirty).toHaveBeenLastCalledWith(false);
  });

  test("selecting the active automatic radio preserves the choice without making a dirty draft", async () => {
    const configuredServer = { ...server, admin_credentials: {} };
    const network = mockNetwork(configuredServer);
    const original = network.getMockImplementation();
    if (!original) throw new Error("Missing network fixture");
    const discovery = deferred<Response>();
    network.mockImplementation((input, init) =>
      String(input) === "/api/admin/mcp/oauth/discover"
        ? discovery.promise
        : original(input, init)
    );
    const dirty = jest.fn();
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        mcpServer={configuredServer}
        onTriggerFetchTools={async () => {}}
        onBusyChange={() => {}}
        onDirtyChange={dirty}
        onSaved={async () => {}}
        onComplete={() => {}}
      />
    );
    const automatic = screen.getByRole("radio", {
      name: copy.oauthSetup.automatic.label,
    });
    expect(automatic).toHaveAttribute("aria-checked", "true");
    await setupUser().click(automatic);
    expect(dirty).toHaveBeenLastCalledWith(false);
    await act(async () =>
      discovery.resolve(
        new Response(
          JSON.stringify({
            status: "metadata_found",
            supports_automatic_registration: false,
            authorization_endpoint: "https://identity.example.com/authorize",
            token_endpoint: "https://identity.example.com/token",
          })
        )
      )
    );
    await waitFor(() =>
      expect(
        screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
      ).toHaveAttribute("aria-checked", "true")
    );
    expect(
      await screen.findByText(copy.discovery.requiresClient)
    ).toBeVisible();
    expect(dirty).toHaveBeenLastCalledWith(false);
  });

  test("keeps an explicit automatic OAuth choice through authentication method changes", async () => {
    mockNetwork(server);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        mcpServer={server}
        recommendation={{
          kind: "oauth",
          transport: MCPTransportType.SSE,
          discovery: {
            status: "metadata_found",
            supports_automatic_registration: false,
            authorization_endpoint: "https://identity.example.com/authorize",
            token_endpoint: "https://identity.example.com/token",
          },
        }}
        onTriggerFetchTools={async () => {}}
        onBusyChange={() => {}}
        onSaved={async () => {}}
        onComplete={() => {}}
      />
    );
    expect(
      screen.getByRole("radio", { name: copy.oauthSetup.ownClient.label })
    ).toHaveAttribute("aria-checked", "true");
    await user.click(
      screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
    );
    await user.click(
      screen.getByRole("combobox", { name: copy.authType.label })
    );
    await user.click(
      screen.getByRole("option", { name: copy.authType.none.label })
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("combobox", { name: copy.authType.label })
    );
    await user.click(screen.getByRole("option", { name: /^OAuth/ }));
    await waitFor(() =>
      expect(
        screen.getByRole("radio", { name: copy.oauthSetup.automatic.label })
      ).toHaveAttribute("aria-checked", "true")
    );
  });

  test("requires a shared API key before resolving and saving the server", async () => {
    mockNetwork(server);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    const resolveServer = jest.fn().mockResolvedValue(server);
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        mcpServer={{ name: server.name, server_url: server.server_url }}
        resolveServer={resolveServer}
        recommendation={{
          kind: "auth_unknown",
          transport: MCPTransportType.SSE,
        }}
        onBusyChange={() => {}}
        onDirtyChange={() => {}}
        onSaved={async () => {}}
        onComplete={() => {}}
        onTriggerFetchTools={async () => {}}
      />
    );
    const proceed = screen.getByTestId("mcp-auth-connect-button");
    expect(proceed).toBeDisabled();
    await user.click(
      screen.getByRole("combobox", { name: copy.authType.label })
    );
    await user.click(
      screen.getByRole("option", { name: copy.authType.apiToken.label })
    );
    await user.click(screen.getByRole("combobox", { name: "Credentials" }));
    await user.click(
      screen.getByRole("option", { name: copy.apiKeyTabs.admin.label })
    );
    await waitFor(() => expect(proceed).toBeDisabled());
    await user.type(
      screen.getByLabelText(copy.sharedApiKey.label, { selector: "input" }),
      "draft-key"
    );
    await waitFor(() => expect(proceed).toBeEnabled());
    await user.click(proceed);
    await waitFor(() => expect(resolveServer).toHaveBeenCalledTimes(1));
  });

  test("keeps detected recommendations visible when users choose other options", async () => {
    mockNetwork(server);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        mcpServer={server}
        recommendation={{
          kind: "oauth",
          transport: MCPTransportType.SSE,
          discovery: {
            status: "metadata_found",
            supports_automatic_registration: true,
            authorization_endpoint: "https://example.com/authorize",
            token_endpoint: "https://example.com/token",
          },
        }}
        onBusyChange={() => {}}
        onDirtyChange={() => {}}
        onSaved={async () => {}}
        onComplete={() => {}}
        onTriggerFetchTools={async () => {}}
      />
    );
    const recommended = messages.craft.llmPopover.recommended.label;
    const oauth = screen.getByRole("combobox", { name: copy.authType.label });
    const automatic = screen.getByRole("radio", {
      name: copy.oauthSetup.automatic.label,
    });
    expect(screen.getAllByText(recommended)).toHaveLength(2);
    expect(automatic).toHaveTextContent(recommended);
    await user.click(
      screen.getByRole("radio", { name: copy.oauthSetup.ownClient.label })
    );
    expect(automatic).toHaveTextContent(recommended);
    expect(
      screen.getByRole("radio", { name: copy.oauthSetup.ownClient.label })
    ).not.toHaveTextContent(recommended);
    await user.click(oauth);
    expect(
      screen.getByRole("option", { name: /^OAuth Recommended$/ })
    ).toHaveTextContent(recommended);
    expect(
      screen.getByRole("option", { name: copy.authType.apiToken.label })
    ).not.toHaveTextContent(recommended);
    await user.click(
      screen.getByRole("option", { name: copy.authType.apiToken.label })
    );
  });

  test("saves and loads tools without a modal footer or step navigation", async () => {
    const configuredServer = {
      ...server,
      auth_type: MCPAuthenticationType.NONE,
    };
    mockNetwork(configuredServer);
    const complete = jest.fn();
    const fetchTools = jest.fn().mockResolvedValue(undefined);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        mcpServer={configuredServer}
        onBusyChange={() => {}}
        onDirtyChange={() => {}}
        onSaved={async () => {}}
        onComplete={complete}
        onTriggerFetchTools={fetchTools}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: messages.actions.mcpSetup.back })
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: copy.submitButton.label })
    );
    await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
    expect(fetchTools).toHaveBeenCalledWith(7);
    expect(
      screen.getByRole("combobox", {
        name: messages.actions.mcpAuthModal.authType.label,
      })
    ).toBeVisible();
  });

  test("read-only authentication cannot edit or submit credentials", async () => {
    mockNetwork(server);
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        readOnly
        mcpServer={server}
        onBusyChange={() => {}}
        onDirtyChange={() => {}}
        onSaved={async () => {}}
        onComplete={() => {}}
        onTriggerFetchTools={async () => {}}
      />
    );
    expect(
      await screen.findByRole("textbox", { name: /^Client ID/ })
    ).toBeDisabled();
    expect(
      screen.getByRole("combobox", { name: copy.authType.label })
    ).toBeDisabled();
    expect(
      screen.queryByTestId("mcp-auth-connect-button")
    ).not.toBeInTheDocument();
  });

  test("read-only API authentication cannot change credential scope", async () => {
    const apiServer = { ...server, auth_type: MCPAuthenticationType.API_TOKEN };
    mockNetwork(apiServer);
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        readOnly
        mcpServer={apiServer}
        onBusyChange={() => {}}
        onDirtyChange={() => {}}
        onSaved={async () => {}}
        onComplete={() => {}}
        onTriggerFetchTools={async () => {}}
      />
    );
    expect(
      await screen.findByRole("combobox", { name: "Credentials" })
    ).toBeDisabled();
    expect(
      screen.getByRole("combobox", { name: copy.authType.label })
    ).toBeDisabled();
  });
});
