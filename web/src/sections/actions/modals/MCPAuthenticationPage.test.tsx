jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: "admin-user" } }),
}));
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
import { mintMcpChatEnableIntent } from "@/sections/actions/mcpChatEnableIntent";
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
  onPublished,
  onComplete,
  onBusyChange,
  onAuthorize,
}: {
  serverId: number;
  onPublished: (serverId: number) => Promise<void>;
  onComplete: () => void;
  onBusyChange: (busy: boolean) => void;
  onAuthorize?: (url: string) => void;
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
      onSaved={async (saved) => onPublished(saved.id)}
      onBusyChange={onBusyChange}
      onComplete={onComplete}
      onAuthorize={onAuthorize}
    />
  ) : null;
}

function Harness({
  configuredServer,
  onPublished,
  onAuthorize,
}: {
  configuredServer: MCPServer;
  onPublished: (serverId: number) => Promise<void>;
  onAuthorize?: (url: string) => void;
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
                onPublished={onPublished}
                onComplete={() => setOpen(false)}
                onBusyChange={setBusy}
                onAuthorize={onAuthorize}
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
            supports_client_metadata: null,
            authorization_endpoint: "https://identity.example.com/authorize",
            token_endpoint: "https://identity.example.com/token",
          }
        )
      );
    }
    if (url === "/api/admin/mcp/setup") {
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
              status: "connected",
              server: configuredServer,
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
  onPublished = jest.fn().mockResolvedValue(undefined),
  user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never })
) {
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
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
    <Harness configuredServer={configuredServer} onPublished={jest.fn()} />
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
    network.mock.calls.some(([url]) => url === "/api/admin/mcp/setup")
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

test("preserves a saved SSE transport and publishes the validated server once", async () => {
  const fetchSpy = mockNetwork(server);
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = await openSetup(server, onPublished);
  const originalLocation = window.location.href;

  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );

  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  expect(onPublished).toHaveBeenCalledWith(7);
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/admin/mcp/setup",
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = await openSetup(server, onPublished);
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
  expect(onPublished).not.toHaveBeenCalled();
});

test("keeps setup open when asynchronous tool discovery fails", async () => {
  mockNetwork(server, "Tool listing timed out");
  const onPublished = jest.fn();
  const user = await openSetup(server, onPublished);
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
      "/api/admin/mcp/setup",
      expect.objectContaining({
        body: expect.stringContaining('"workspace":"support"'),
      })
    )
  );
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
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

test("compares failed retries against the unchanged saved configuration", async () => {
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
      fetchSpy.mock.calls.filter(([url]) => url === "/api/admin/mcp/setup")
    ).toHaveLength(2)
  );
  const submissions = fetchSpy.mock.calls.filter(
    ([url]) => url === "/api/admin/mcp/setup"
  );
  expect(JSON.parse(String(submissions[1]?.[1]?.body))).toEqual(
    expect.objectContaining({
      oauth_client_id: "registered-client",
      oauth_client_id_changed: false,
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
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
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  // The stored token shows as a tag; the input itself stays empty.
  expect(
    await screen.findByLabelText(copy.sharedApiKey.label, {
      selector: "input",
    })
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
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
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
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  // The stored token shows as a tag; the input itself stays empty.
  expect(
    await screen.findByLabelText(copy.sharedApiKey.label, {
      selector: "input",
    })
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
  expect(onPublished).not.toHaveBeenCalled();
  expect(
    fetchSpy.mock.calls.filter(([url]) => url === "/api/admin/mcp/setup")
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
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
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

test("keeps setup open while the published server refresh is pending", async () => {
  mockNetwork(server);
  const discovery = deferred<void>();
  const onPublished = jest.fn(() => discovery.promise);
  const user = await openSetup(server, onPublished);
  await user.click(
    screen.getByRole("button", {
      name: copy.submitButton.label,
    })
  );
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
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
    ([url]) => url === "/api/admin/mcp/setup"
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
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
    fetchSpy.mock.calls.some(([url]) => url === "/api/admin/mcp/setup")
  ).toBe(false);
  expect(onPublished).not.toHaveBeenCalled();
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = setupUser();
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
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
    fetchSpy.mock.calls.some(([url]) => url === "/api/admin/mcp/setup")
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
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
});

test("automatic setup can turn off the client metadata document", async () => {
  const configuredServer = { ...server, admin_credentials: {} };
  const fetchSpy = mockNetwork(configuredServer);
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = setupUser();
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
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
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
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
  const onPublished = jest.fn().mockResolvedValue(undefined);
  const user = await openSetup(
    configuredServer,
    onPublished,
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
  await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  const submission = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
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
    ([url]) => url === "/api/admin/mcp/setup"
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
        supports_client_metadata: null,
        authorization_endpoint: "https://identity.example.com/authorize",
        token_endpoint: "https://identity.example.com/token",
      },
    });
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    render(
      <Harness configuredServer={configuredServer} onPublished={jest.fn()} />
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
      supports_client_metadata: null,
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
    <Harness configuredServer={configuredServer} onPublished={jest.fn()} />
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

test("rejected client metadata documents fall back to automatic registration", async () => {
  const configuredServer: MCPServer = {
    ...server,
    admin_credentials: {},
  };
  const authorizationUrl = "https://identity.example.com/authorize?client=dcr";
  let finishRetry: () => void = () => {};
  const retryResponse = new Promise<Response>((resolve) => {
    finishRetry = () =>
      resolve(
        new Response(
          JSON.stringify({
            status: "authorization_required",
            authorization_url: authorizationUrl,
          })
        )
      );
  });
  const network = mockNetwork(configuredServer);
  const fallback = network.getMockImplementation();
  network.mockImplementation(async (input, init) => {
    if (String(input) === "/api/admin/mcp/setup") {
      return JSON.parse(String(init?.body)).oauth_cimd_enabled
        ? new Response(
            JSON.stringify({
              detail: "Invalid client_id",
              oauth_error: "client_metadata_rejected",
            }),
            { status: 400 }
          )
        : retryResponse;
    }
    if (!fallback) throw new Error("Missing network fixture");
    return fallback(input, init);
  });
  const onPublished = jest.fn();
  const onAuthorize = jest.fn();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness
      configuredServer={configuredServer}
      onPublished={onPublished}
      onAuthorize={onAuthorize}
    />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByRole("radio", { name: copy.oauthSetup.automatic.label });
  const cimdSwitch = screen.getByRole("switch", {
    name: new RegExp(`^${copy.cimd.label}`),
  });
  expect(cimdSwitch).toBeChecked();
  const connect = screen.getByRole("button", {
    name: copy.submitButton.label,
  });
  await user.click(connect);
  const submissions = () =>
    network.mock.calls
      .filter(([url]) => url === "/api/admin/mcp/setup")
      .map(([, init]) => JSON.parse(String(init?.body)).oauth_cimd_enabled);
  await waitFor(() => expect(submissions()).toEqual([true, false]));
  expect(connect).toBeDisabled();
  finishRetry();
  await waitFor(() =>
    expect(onAuthorize).toHaveBeenCalledWith(authorizationUrl)
  );
  expect(onPublished).not.toHaveBeenCalled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("retrying unavailable discovery refreshes support while preserving automatic setup", async () => {
  const options: { discovery: MCPOAuthDiscovery } = {
    discovery: {
      status: "unreachable",
      supports_automatic_registration: null,
      supports_client_metadata: null,
      authorization_endpoint: null,
      token_endpoint: null,
    },
  };
  const configuredServer = { ...server, admin_credentials: {} };
  const fetchSpy = mockNetwork(configuredServer, undefined, false, options);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} onPublished={jest.fn()} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByText(copy.discovery.unreachable);
  options.discovery = {
    ...options.discovery,
    status: "metadata_found",
    supports_automatic_registration: true,
    supports_client_metadata: null,
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

test("a provider that cannot use client metadata starts with automatic registration", async () => {
  const configuredServer = { ...server, admin_credentials: {} };
  const network = mockNetwork(configuredServer, undefined, false, {
    discovery: {
      status: "metadata_found",
      supports_automatic_registration: true,
      supports_client_metadata: false,
      authorization_endpoint: "https://example.com/authorize",
      token_endpoint: "https://example.com/token",
    },
  });
  const onPublished = jest.fn();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <Harness configuredServer={configuredServer} onPublished={onPublished} />
  );
  await user.click(screen.getByRole("button", { name: "Open setup" }));
  await screen.findByRole("radio", { name: copy.oauthSetup.automatic.label });
  await waitFor(() =>
    expect(
      screen.getByRole("switch", { name: new RegExp(`^${copy.cimd.label}`) })
    ).not.toBeChecked()
  );
  await user.click(
    screen.getByRole("button", { name: copy.submitButton.label })
  );
  await waitFor(() => expect(onPublished).toHaveBeenCalled());
  const submissions = network.mock.calls
    .filter(([url]) => url === "/api/admin/mcp/setup")
    .map(([, init]) => JSON.parse(String(init?.body)).oauth_cimd_enabled);
  expect(submissions).toEqual([false]);
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
      ([url]) => String(url) === "/api/admin/mcp/setup"
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
          supports_client_metadata: null,
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
        onSaved={async () => {}}
        onBusyChange={() => {}}
        onDirtyChange={dirty}

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
        onSaved={async () => {}}
        onBusyChange={() => {}}
        onDirtyChange={dirty}

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
            supports_client_metadata: null,
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
            supports_client_metadata: null,
            authorization_endpoint: "https://identity.example.com/authorize",
            token_endpoint: "https://identity.example.com/token",
          },
        }}
        onSaved={async () => {}}
        onBusyChange={() => {}}

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
    const onCreate = jest.fn().mockResolvedValue(server);
    render(
      <MCPAuthenticationPage
        active
        variant="page"
        mcpServer={{ name: server.name, server_url: server.server_url }}
        onCreate={onCreate}
        recommendation={{
          kind: "auth_unknown",
          transport: MCPTransportType.SSE,
        }}
        onBusyChange={() => {}}
        onDirtyChange={() => {}}
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
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
  });

  test.each([true, false])(
    "offers pass-through with collapsed connection settings only when OAuth login is enabled: %s",
    async (oauthEnabled) => {
      mockNetwork(server, undefined, oauthEnabled);
      const user = setupUser({
        pointerEventsCheck: PointerEventsCheckLevel.Never,
      });
      render(
        <MCPAuthenticationPage
          active
          variant="page"
          mcpServer={server}
          recommendation={{
            kind: "public",
            transport: MCPTransportType.SSE,
            tool_count: 3,
            server_name: server.name,
          }}
          onBusyChange={() => {}}

          onComplete={() => {}}
          onSaved={async () => {}}
        />
      );
      await waitFor(() =>
        expect(global.fetch).toHaveBeenCalledWith("/api/auth/type")
      );
      expect(
        screen.getByRole("button", { name: "Expand Advanced settings" })
      ).toBeVisible();
      const method = screen.getByRole("combobox", {
        name: copy.authType.label,
      });
      expect(method).toHaveValue(copy.authType.none.label);
      await user.click(method);
      const option = screen.queryByRole("option", {
        name: copy.authType.ptOauth.label,
      });
      if (oauthEnabled) {
        expect(option).toBeVisible();
      } else {
        expect(option).not.toBeInTheDocument();
      }
    }
  );

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
            supports_client_metadata: null,
            authorization_endpoint: "https://example.com/authorize",
            token_endpoint: "https://example.com/token",
          },
        }}
        onBusyChange={() => {}}
        onDirtyChange={() => {}}

        onComplete={() => {}}
        onSaved={async () => {}}
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
    const onPublished = jest.fn().mockResolvedValue(undefined);
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

        onComplete={complete}
        onSaved={async (saved) => onPublished(saved.id)}
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
    expect(onPublished).toHaveBeenCalledWith(7);
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

        onComplete={() => {}}
        onSaved={async () => {}}
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

        onComplete={() => {}}
        onSaved={async () => {}}
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

test("restores automatic OAuth setup after registration without a dirty form", async () => {
  const configuredServer: MCPServer = {
    ...server,
    oauth_setup_mode: "automatic",
    status: MCPServerStatus.CONNECTED,
    admin_credentials: { client_id: "********", client_secret: "********" },
  };
  mockNetwork(configuredServer);
  const dirty = jest.fn();
  render(
    <MCPAuthenticationPage
      active
      variant="page"
      mcpServer={configuredServer}
      onSaved={async () => {}}
      onBusyChange={() => {}}
      onDirtyChange={dirty}
      onComplete={() => {}}
    />
  );
  const automatic = await screen.findByRole("radio", {
    name: new RegExp(`^${copy.oauthSetup.automatic.label}`),
  });
  expect(automatic).toHaveAttribute("aria-checked", "true");
  expect(
    screen.queryByLabelText(copy.clientId.label, { exact: false })
  ).not.toBeInTheDocument();
  await setupUser().click(automatic);
  expect(dirty).toHaveBeenLastCalledWith(false);
});

test("an unverified Chat-enable token cannot enable Chat during staged authentication", async () => {
  const configuredServer: MCPServer = {
    ...server,
    auth_type: MCPAuthenticationType.NONE,
    status: MCPServerStatus.CONNECTED,
    tool_count: 0,
  };
  const network = mockNetwork(configuredServer);
  const onPublished = jest.fn().mockResolvedValue(undefined);
  render(
    <MCPAuthenticationPage
      active
      variant="page"
      mcpServer={configuredServer}
      chatEnableIntent="pending-chat-intent"
      onSaved={async (saved) => onPublished(saved.id)}
      onBusyChange={() => {}}
      onComplete={() => {}}
    />
  );
  const save = await screen.findByTestId("mcp-auth-connect-button");
  expect(save).toBeEnabled();
  await setupUser().click(save);
  await waitFor(() => expect(onPublished).toHaveBeenCalledWith(7));
  const submission = network.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
  );
  expect(JSON.parse(String(submission?.[1]?.body))).not.toHaveProperty(
    "enable_chat"
  );
});

test("stages pending URL and metadata changes and publishes only after validation succeeds", async () => {
  const draftServer: MCPServer = {
    ...server,
    server_url: "https://replacement.example.com/mcp",
    auth_type: MCPAuthenticationType.NONE,
    admin_credentials: undefined,
  };
  const published = {
    ...draftServer,
    name: "Replacement MCP",
    status: MCPServerStatus.CONNECTED,
  };
  const network = mockNetwork(draftServer);
  const fallback = network.getMockImplementation();
  let fail = true;
  network.mockImplementation(async (input, init) => {
    if (String(input) === "/api/admin/mcp/setup") {
      return fail
        ? new Response(JSON.stringify({ detail: "Tool discovery failed" }), {
            status: 502,
          })
        : new Response(
            JSON.stringify({ status: "connected", server: published })
          );
    }
    if (!fallback) throw new Error("Missing network fixture");
    return fallback(input, init);
  });
  const saved = jest.fn().mockResolvedValue(undefined);
  const complete = jest.fn();
  render(
    <MCPAuthenticationPage
      active
      variant="page"
      mcpServer={draftServer}
      configurationDraft={{
        name: "Replacement MCP",
        server_url: draftServer.server_url,
        enable_chat: true,
      }}
      onSaved={saved}
      onComplete={complete}
      onBusyChange={() => {}}
    />
  );
  const user = setupUser();
  await user.click(screen.getByTestId("mcp-auth-connect-button"));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Tool discovery failed"
  );
  expect(saved).not.toHaveBeenCalled();
  expect(complete).not.toHaveBeenCalled();
  expect(
    network.mock.calls.some(([url]) => url === "/api/admin/mcp/oauth/discover")
  ).toBe(false);
  const first = network.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
  );
  expect(JSON.parse(String(first?.[1]?.body))).toEqual(
    expect.objectContaining({
      name: "Replacement MCP",
      server_url: draftServer.server_url,
      existing_server_id: 7,
      enable_chat: true,
    })
  );
  fail = false;
  await user.click(screen.getByTestId("mcp-auth-connect-button"));
  await waitFor(() => expect(saved).toHaveBeenCalledWith(published));
  expect(complete).toHaveBeenCalledTimes(1);
  expect(
    network.mock.calls
      .filter(([, options]) => options?.method === "POST")
      .every(([url]) => url === "/api/admin/mcp/setup")
  ).toBe(true);
});

test("explicit Chat disable overrides an earlier verified enable intent", async () => {
  const configuredServer = { ...server, auth_type: MCPAuthenticationType.NONE };
  const network = mockNetwork(configuredServer);
  const intent = mintMcpChatEnableIntent({ userId: "admin-user", serverId: 7 });
  const saved = jest.fn().mockResolvedValue(undefined);
  render(
    <MCPAuthenticationPage
      active
      variant="page"
      mcpServer={configuredServer}
      configurationDraft={{ enable_chat: false }}
      chatEnableIntent={intent}
      onSaved={saved}
      onBusyChange={() => {}}
      onComplete={() => {}}
    />
  );
  await setupUser().click(await screen.findByTestId("mcp-auth-connect-button"));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  const submission = network.mock.calls.find(
    ([url]) => url === "/api/admin/mcp/setup"
  );
  expect(JSON.parse(String(submission?.[1]?.body)).enable_chat).toBe(false);
});

test.each([
  MCPAuthenticationPerformer.PER_USER,
  MCPAuthenticationPerformer.ADMIN,
])(
  "accepts a replacement API token after a URL change clears headers (%s)",
  async (performer) => {
    const configuredServer: MCPServer = {
      ...server,
      server_url: "https://replacement.example.com/mcp",
      auth_type: MCPAuthenticationType.API_TOKEN,
      auth_performer: performer,
      admin_credentials: undefined,
      user_credentials: undefined,
      status: MCPServerStatus.AWAITING_AUTH,
      auth_template: {
        headers: { Authorization: "" },
        required_fields: ["api_key"],
      },
    };
    const fetchSpy = mockNetwork(configuredServer);
    const onPublished = jest.fn().mockResolvedValue(undefined);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    render(
      <Harness configuredServer={configuredServer} onPublished={onPublished} />
    );
    await user.click(screen.getByRole("button", { name: "Open setup" }));
    const token = await screen.findByLabelText(copy.sharedApiKey.label);
    expect(token).toHaveValue("");
    await user.type(token, "replacement-token");
    await user.click(
      screen.getByRole("button", { name: copy.submitButton.label })
    );
    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(server.id));
    const submission = fetchSpy.mock.calls.find(
      ([url]) => url === "/api/admin/mcp/setup"
    );
    expect(JSON.parse(String(submission?.[1]?.body))).toEqual(
      expect.objectContaining({
        server_url: configuredServer.server_url,
        auth_template: {
          headers: { Authorization: "Bearer {api_key}" },
          required_fields: ["api_key"],
        },
        ...(performer === MCPAuthenticationPerformer.ADMIN
          ? { api_token: "replacement-token" }
          : { admin_credentials: { api_key: "replacement-token" } }),
      })
    );
  }
);
