import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import OpenAPIPluginCreateModal from "@/sections/plugins/OpenAPIPluginCreateModal";
import type { ToolSnapshot } from "@/lib/tools/types";

let mockFullAdmin = false;
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: mockFullAdmin }),
}));
beforeEach(() => {
  mockFullAdmin = false;
});

const definition = {
  openapi: "3.0.0",
  info: { title: "Release API", version: "1.0" },
  servers: [{ url: "https://releases.example.com" }],
  paths: {
    "/releases": {
      get: {
        operationId: "listReleases",
        summary: "List releases",
        responses: { "200": { description: "Releases" } },
      },
    },
  },
};

afterEach(() => jest.restoreAllMocks());

test.each([{ customHeaders: [] }, { customHeaders: null }])(
  "attaches a full admin's new action to default Chat with $customHeaders headers",
  async ({ customHeaders }) => {
    mockFullAdmin = true;
    const user = setupUser();
    const onCreated = jest.fn();
    const writes: { path: string; body: unknown }[] = [];
    let created = false;
    jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (init?.body)
        writes.push({ path, body: JSON.parse(String(init.body)) });
      if (path === "/api/admin/default-assistant/configuration")
        return new Response(JSON.stringify({ tool_ids: [99] }));
      if (path === "/api/admin/default-assistant")
        return new Response(JSON.stringify({ tool_ids: [99, 42] }));
      if (path === "/api/tool/openapi")
        return new Response(
          JSON.stringify(
            created
              ? [{ id: 42, name: "Release API", custom_headers: customHeaders }]
              : []
          )
        );
      if (path === "/api/admin/tool/custom/validate")
        return new Response(JSON.stringify({ methods: [] }));
      if (path === "/api/admin/tool/custom") {
        created = true;
        return new Response(JSON.stringify({ id: 42 }));
      }
      throw new Error(`Unexpected request ${path}`);
    });
    render(
      <OpenAPIPluginCreateModal
        open
        onClose={jest.fn()}
        onCreated={onCreated}
      />
    );
    fireEvent.change(await screen.findByRole("textbox"), {
      target: { value: JSON.stringify(definition) },
    });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Add Action" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
    expect(writes).toContainEqual({
      path: "/api/admin/default-assistant",
      body: { tool_ids: [99, 42] },
    });
    expect(
      writes.findIndex((write) => write.path === "/api/admin/tool/custom")
    ).toBeLessThan(
      writes.findIndex((write) => write.path === "/api/admin/default-assistant")
    );
  }
);

test.each(["mounted", "disposed"])(
  "creates a no-auth action for a scoped creator and reports completion only while %s",
  async (session) => {
    const user = setupUser();
    const onCreated = jest.fn();
    const onClose = jest.fn();
    const reload = deferred<Response>();
    let created = false;
    let createBody: unknown;
    jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/tool/openapi")
        return created ? reload.promise : new Response("[]");
      if (path === "/api/admin/tool/custom/validate")
        return new Response(JSON.stringify({ methods: [] }));
      if (path === "/api/admin/tool/custom") {
        createBody = JSON.parse(String(init?.body));
        created = true;
        return new Response(JSON.stringify({ id: 42, name: "Release API" }));
      }
      throw new Error(`Unexpected request ${path}`);
    });
    const { unmount } = render(
      <OpenAPIPluginCreateModal open onClose={onClose} onCreated={onCreated} />
    );
    fireEvent.change(await screen.findByRole("textbox"), {
      target: { value: JSON.stringify(definition) },
    });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(createBody).toBeUndefined();
    expect(
      screen.getByRole("dialog", { name: "Connect to Release API" })
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("textbox")).toHaveValue(
      JSON.stringify(definition, null, 2)
    );
    expect(createBody).toBeUndefined();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      screen.getByRole("dialog", { name: "Connect to Release API" })
    ).toBeVisible();
    expect(createBody).toBeUndefined();
    await user.click(await screen.findByRole("button", { name: "Add Action" }));
    await waitFor(() =>
      expect(createBody).toEqual({
        name: "Release API",
        definition,
        custom_headers: [],
        passthrough_auth: false,
      })
    );
    expect(onCreated).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    if (session === "disposed") unmount();
    await act(async () => {
      reload.resolve(
        new Response(
          JSON.stringify([
            {
              id: 42,
              name: "Release API",
              custom_headers: [],
              passthrough_auth: false,
              oauth_config_id: null,
              permissions: { authenticate: false },
            },
          ])
        )
      );
    });
    if (session === "mounted")
      await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
    else {
      expect(onCreated).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
    }
  }
);

test("shows creation failures without completing or closing the form", async () => {
  const user = setupUser();
  const onCreated = jest.fn();
  const onClose = jest.fn();
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/tool/openapi") return new Response("[]");
    if (path === "/api/admin/tool/custom/validate")
      return new Response(JSON.stringify({ methods: [] }));
    return new Response(
      JSON.stringify({ detail: "Schema name already exists" }),
      { status: 400 }
    );
  });
  render(
    <OpenAPIPluginCreateModal open onClose={onClose} onCreated={onCreated} />
  );
  fireEvent.change(await screen.findByRole("textbox"), {
    target: { value: JSON.stringify(definition) },
  });
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(await screen.findByRole("button", { name: "Add Action" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Add Action" })).toBeEnabled()
  );
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(onCreated).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
});

test("keeps OAuth settings through Back and saves them only on final creation", async () => {
  const onCreated = jest.fn();
  let created = false;
  const writes: { path: string; body: unknown }[] = [];
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path === "/api/tool/openapi")
      return new Response(
        JSON.stringify(
          created
            ? [
                {
                  id: 42,
                  name: "Release API",
                  permissions: { authenticate: true },
                },
              ]
            : []
        )
      );
    if (path === "/api/admin/tool/custom/validate")
      return new Response(JSON.stringify({ methods: [] }));
    if (path === "/api/admin/oauth-config/pkce-support")
      return new Response(JSON.stringify({ status: "supported" }));
    writes.push({ path, body: JSON.parse(String(init?.body)) });
    if (path === "/api/admin/tool/custom") {
      created = true;
      return new Response(JSON.stringify({ id: 42, name: "Release API" }));
    }
    if (path === "/api/admin/oauth-config/create")
      return new Response(JSON.stringify({ id: 99 }));
    if (path === "/api/admin/tool/custom/42")
      return new Response(JSON.stringify({ id: 42 }));
    throw new Error(`Unexpected request ${path}`);
  });
  render(
    <OpenAPIPluginCreateModal open onClose={jest.fn()} onCreated={onCreated} />
  );
  const user = setupUser();
  fireEvent.change(await screen.findByRole("textbox"), {
    target: { value: JSON.stringify(definition) },
  });
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(await screen.findByRole("combobox"));
  await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
  fireEvent.change(
    await screen.findByRole("textbox", { name: "Authorization URL" }),
    { target: { value: "https://identity.example.com/authorize" } }
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Token URL" }), {
    target: { value: "https://identity.example.com/token" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "OAuth Client ID" }), {
    target: { value: "release-client" },
  });
  fireEvent.change(screen.getByLabelText("OAuth Client Secret"), {
    target: { value: "release-secret" },
  });
  await user.click(screen.getByRole("button", { name: "Back" }));
  await screen.findByRole("dialog", { name: "Add an OpenAPI plugin" });
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(
    await screen.findByRole("textbox", { name: "OAuth Client ID" })
  ).toHaveValue("release-client");
  expect(writes).toEqual([]);
  const submit = screen.getByRole("button", { name: "Add Action" });
  await waitFor(() => expect(submit).toBeEnabled());
  await user.click(submit);
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
  expect(writes).toContainEqual({
    path: "/api/admin/oauth-config/create",
    body: expect.objectContaining({
      client_id: "release-client",
      client_secret: "release-secret",
    }),
  });
  expect(writes).toContainEqual({
    path: "/api/admin/tool/custom/42",
    body: { custom_headers: [], passthrough_auth: false, oauth_config_id: 99 },
  });
});

describe("authentication save retries", () => {
  test.each(["oauth", "none", "schema edit", "failed refresh"])(
    "retains acknowledged OAuth after final refresh failure and retries with %s",
    async (retry) => {
      const user = setupUser();
      const onCreated = jest.fn();
      let tool: ToolSnapshot | null = null;
      let toolCreates = 0;
      let configCreates = 0;
      const configs = new Set<number>();
      const updates: Partial<ToolSnapshot>[] = [];
      let failRefresh = false;
      jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
        const path = String(input);
        if (path === "/api/settings" || path === "/api/enterprise-settings")
          return new Response("{}");
        if (path === "/api/auth/type")
          return new Response(JSON.stringify({ oauth_enabled: true }));
        if (path === "/api/tool/openapi") {
          if (failRefresh) {
            failRefresh = false;
            return new Response(
              JSON.stringify({ detail: "List refresh failed" }),
              {
                status: 503,
              }
            );
          }
          return new Response(JSON.stringify(tool ? [tool] : []));
        }
        if (path === "/api/admin/tool/custom/validate")
          return new Response(JSON.stringify({ methods: [] }));
        if (path === "/api/admin/tool/custom") {
          toolCreates += 1;
          tool = {
            id: 42,
            name: "Release API",
            display_name: "Release API",
            description: "",
            definition,
            custom_headers: [],
            passthrough_auth: false,
            oauth_config_id: null,
            in_code_tool_id: null,
            enabled: true,
            chat_selectable: true,
            agent_creation_selectable: true,
            default_enabled: false,
            permissions: { authenticate: true },
          };
          return new Response(JSON.stringify(tool));
        }
        if (path === "/api/admin/oauth-config/create") {
          configCreates += 1;
          configs.add(99);
          return new Response(JSON.stringify({ id: 99 }));
        }
        if (path === "/api/admin/oauth-config/99")
          return new Response(
            JSON.stringify(
              configs.has(99) ? { id: 99 } : { detail: "Config deleted" }
            ),
            { status: configs.has(99) ? 200 : 404 }
          );
        if (path === "/api/admin/tool/custom/42" && tool) {
          const body: Partial<ToolSnapshot> = JSON.parse(String(init?.body));
          updates.push(body);
          const oauthConfigId = body.oauth_config_id ?? null;
          if (oauthConfigId && !configs.has(oauthConfigId))
            return new Response(JSON.stringify({ detail: "Config deleted" }), {
              status: 404,
            });
          if (tool.oauth_config_id && tool.oauth_config_id !== oauthConfigId)
            configs.delete(tool.oauth_config_id);
          tool = { ...tool, ...body, oauth_config_id: oauthConfigId };
          if (updates.length === 1) failRefresh = true;
          return new Response(JSON.stringify(tool));
        }
        throw new Error(`Unexpected request ${path}`);
      });
      render(
        <OpenAPIPluginCreateModal
          open
          onClose={jest.fn()}
          onCreated={onCreated}
        />
      );
      fireEvent.change(await screen.findByRole("textbox"), {
        target: { value: JSON.stringify(definition) },
      });
      await user.click(screen.getByRole("button", { name: "Continue" }));
      await user.click(await screen.findByRole("combobox"));
      await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
      fireEvent.change(
        await screen.findByRole("textbox", { name: "Authorization URL" }),
        {
          target: { value: "https://identity.example.com/authorize" },
        }
      );
      fireEvent.change(screen.getByRole("textbox", { name: "Token URL" }), {
        target: { value: "https://identity.example.com/token" },
      });
      fireEvent.change(
        screen.getByRole("textbox", { name: "OAuth Client ID" }),
        {
          target: { value: "release-client" },
        }
      );
      fireEvent.change(screen.getByLabelText("OAuth Client Secret"), {
        target: { value: "release-secret" },
      });
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Add Action" })).toBeEnabled()
      );
      await user.click(screen.getByRole("button", { name: "Add Action" }));
      await waitFor(() => expect(failRefresh).toBe(false));
      expect(onCreated).not.toHaveBeenCalled();
      expect(
        await screen.findByText("An error occurred while fetching the data.")
      ).toBeVisible();
      expect(configs.has(99)).toBe(true);
      if (retry === "failed refresh") {
        failRefresh = true;
        const updateCount = updates.length;
        await user.click(screen.getByRole("button", { name: "Add Action" }));
        await waitFor(() => expect(failRefresh).toBe(false));
        expect(updates).toHaveLength(updateCount);
        expect(onCreated).not.toHaveBeenCalled();
      }
      if (retry === "none") {
        await user.click(screen.getByRole("combobox"));
        await user.keyboard("{ArrowDown}{Enter}");
      } else if (retry === "schema edit") {
        await user.click(screen.getByRole("button", { name: "Back" }));
        fireEvent.change(await screen.findByRole("textbox"), {
          target: {
            value: JSON.stringify({
              ...definition,
              info: {
                ...definition.info,
                description: "Updated release schema",
              },
            }),
          },
        });
        await user.click(screen.getByRole("button", { name: "Continue" }));
      }
      await user.click(screen.getByRole("button", { name: "Add Action" }));
      await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
      expect(toolCreates).toBe(1);
      expect(configCreates).toBe(1);
      expect(configs.has(99)).toBe(retry !== "none");
      expect(tool).toEqual(
        expect.objectContaining({
          oauth_config_id: retry === "none" ? null : 99,
          custom_headers: [],
          passthrough_auth: false,
        })
      );
      if (retry === "none")
        expect(updates).toContainEqual({
          custom_headers: [],
          passthrough_auth: false,
          oauth_config_id: null,
        });
      else
        expect(updates[1]).toEqual(
          expect.objectContaining({ oauth_config_id: 99 })
        );
    }
  );
});
