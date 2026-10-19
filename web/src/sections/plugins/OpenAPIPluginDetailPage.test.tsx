import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import type { ToolSnapshot } from "@/lib/tools/types";
import { ToastProvider, toast } from "@opal/layouts";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import OpenAPIPluginDetailPage from "@/sections/plugins/OpenAPIPluginDetailPage";

const mockPush = jest.fn();
const mockReplace = jest.fn();
const mockRouter = { push: mockPush, replace: mockReplace };
let mockQuery = new URLSearchParams();
jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => mockRouter,
  useSearchParams: () => mockQuery,
}));

const definition = {
  openapi: "3.0.0",
  info: {
    title: "Release API",
    description: "Read release status",
    version: "1.0",
  },
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
const configuredTool: ToolSnapshot = {
  id: 42,
  name: "Release API",
  display_name: "Release API",
  description: "Read release status",
  definition,
  custom_headers: [],
  passthrough_auth: false,
  oauth_config_id: 7,
  in_code_tool_id: null,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { edit: true, delete: true, toggle: true, authenticate: true },
};

let tool: ToolSnapshot;
let writes: { path: string; body: unknown; method?: string }[];
let listResponse: (() => Promise<Response>) | undefined;
let oauthResponse: ((id: number) => Promise<Response>) | undefined;
let failWrite: string | null;
let failNextLink: boolean;
let failNextAuthRefresh: boolean;
let failRefreshAfterWrite: boolean;
let configCreates: number;
let configs: Set<number>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

beforeEach(() => {
  toast.clearAll();
  mockQuery = new URLSearchParams();
  mockPush.mockClear();
  mockReplace.mockClear();
  tool = { ...configuredTool };
  writes = [];
  listResponse = undefined;
  oauthResponse = undefined;
  failWrite = null;
  failNextLink = false;
  failNextAuthRefresh = false;
  failRefreshAfterWrite = false;
  configCreates = 0;
  configs = new Set([7]);
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path === "/api/tool/openapi") {
      if (failNextAuthRefresh) {
        failNextAuthRefresh = false;
        return json({ detail: "List refresh failed" }, 503);
      }
      return listResponse ? listResponse() : json([tool]);
    }
    if (path === "/api/settings") return json({});
    if (path === "/api/enterprise-settings") return json({});
    if (path === "/api/auth/type") return json({ oauth_enabled: true });
    if (path.startsWith("/api/admin/oauth-config/") && !init?.method) {
      const id = Number(path.split("/").at(-1));
      if (oauthResponse) return oauthResponse(id);
      if (!configs.has(id)) return json({ detail: "Config deleted" }, 404);
      return json({
        id,
        name: "Release OAuth",
        authorization_url: "https://identity.example.com/authorize",
        token_url: "https://identity.example.com/token",
        scopes: ["read"],
        has_client_credentials: true,
      });
    }
    if (path === "/api/admin/tool/custom/validate")
      return json({
        methods: [
          {
            name: "listReleases",
            summary: "List releases",
            method: "GET",
            path: "/releases",
          },
        ],
      });
    if (init?.method && init.method !== "GET") {
      const body: unknown = init.body ? JSON.parse(String(init.body)) : null;
      writes.push({ path, body, method: init.method });
      if (failWrite) return json({ detail: failWrite }, 400);
      if (init.method === "DELETE") return json(true);
      if (path === "/api/admin/tool/status")
        return json({ updated_count: 1, tool_ids: [42] });
      if (path === "/api/admin/oauth-config/7") return json({ id: 7 });
      if (path === "/api/admin/oauth-config/create") {
        configCreates += 1;
        const id = 98 + configCreates;
        configs.add(id);
        return json({ id });
      }
      if (path.startsWith("/api/admin/oauth-config/")) {
        const id = Number(path.split("/").at(-1));
        return configs.has(id)
          ? json({ id })
          : json({ detail: "Config deleted" }, 404);
      }
      if (path === "/api/admin/tool/custom/42") {
        const update: Partial<ToolSnapshot> = JSON.parse(String(init.body));
        if (update.oauth_config_id && failNextLink) {
          failNextLink = false;
          return json({ detail: "Link failed" }, 503);
        }
        const oauthConfigId = update.oauth_config_id ?? null;
        if (oauthConfigId && !configs.has(oauthConfigId))
          return json({ detail: "Config deleted" }, 404);
        if (tool.oauth_config_id && tool.oauth_config_id !== oauthConfigId)
          configs.delete(tool.oauth_config_id);
        tool = { ...tool, ...update, oauth_config_id: oauthConfigId };
        if (failRefreshAfterWrite) {
          failRefreshAfterWrite = false;
          failNextAuthRefresh = true;
        }
      }
      return json({ ...tool, permissions: undefined });
    }
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => {
  toast.clearAll();
  jest.restoreAllMocks();
});

function BackgroundRefresh() {
  const { mutate } = useSWRConfig();
  return (
    <button onClick={() => void mutate(SWR_KEYS.openApiTools)}>
      Refresh tools
    </button>
  );
}

async function findEditorTab(name: string) {
  return screen.findByRole("tab", {
    name:
      name === "Edit authentication"
        ? "Authentication"
        : name === "Edit schema"
          ? "Configuration"
          : "Configuration",
  });
}

async function findToolsPreview() {
  await setupUser().click(await screen.findByRole("tab", { name: "Tools" }));
  return screen.findByText("listReleases");
}

describe("detail modal", () => {
  test("saving metadata preserves availability changed by another administrator", async () => {
    render(<OpenAPIPluginDetailPage toolId={42} />);
    const user = setupUser();
    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Updated API");
    tool = { ...tool, enabled: false };
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual(
      expect.objectContaining({
        path: "/api/admin/tool/custom/42",
        body: expect.objectContaining({ name: "Updated API" }),
      })
    );
    expect(tool.enabled).toBe(false);
  });

  test("does not overwrite concurrent metadata after reverting a draft", async () => {
    render(<OpenAPIPluginDetailPage toolId={42} />);
    const name = await screen.findByRole("textbox", { name: "Name" });
    fireEvent.change(name, { target: { value: "Temporary name" } });
    fireEvent.change(name, { target: { value: configuredTool.name } });
    fireEvent.click(
      screen.getByRole("switch", { name: "Enable for workspace" })
    );
    tool = { ...tool, name: "Another administrator's name" };
    await setupUser().click(
      screen.getByRole("button", { name: "Save Changes" })
    );
    await waitFor(() =>
      expect(writes).toContainEqual({
        path: "/api/admin/tool/status",
        method: "PATCH",
        body: { tool_ids: [42], enabled: false },
      })
    );
    expect(
      writes.some((write) => write.path === "/api/admin/tool/custom/42")
    ).toBe(false);
    expect(tool.name).toBe("Another administrator's name");
  });

  test("configuration saves metadata, schema, and availability together", async () => {
    render(<OpenAPIPluginDetailPage toolId={42} />);
    const user = setupUser();
    const availability = await screen.findByRole("switch", {
      name: "Enable for workspace",
    });
    const updatedDefinition = {
      ...definition,
      info: { ...definition.info, version: "2.0" },
    };
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Updated API" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      { target: { value: JSON.stringify(updatedDefinition) } }
    );
    await user.click(availability);
    expect(writes).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(writes).toContainEqual({
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: {
          name: "Updated API",
          description: "Read release status",
          definition: updatedDefinition,
          oauth_config_id: 7,
        },
      })
    );
    await waitFor(() =>
      expect(writes).toContainEqual({
        path: "/api/admin/tool/status",
        method: "PATCH",
        body: { tool_ids: [42], enabled: false },
      })
    );
  });

  test.each(["metadata", "schema", "authentication"] as const)(
    "guards %s drafts in the same frame and retains them when staying",
    async (editor) => {
      const user = setupUser();
      render(<OpenAPIPluginDetailPage toolId={42} />);
      await user.click(
        await findEditorTab(
          editor === "metadata"
            ? "Edit"
            : editor === "schema"
              ? "Edit schema"
              : "Edit authentication"
        )
      );
      if (editor === "authentication") {
        await waitFor(() =>
          expect(
            screen.getByRole("textbox", { name: "Token URL" })
          ).toHaveValue("https://identity.example.com/token")
        );
      }
      const input =
        editor === "schema"
          ? screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
          : screen.getByRole("textbox", {
              name: editor === "metadata" ? "Name" : "Token URL",
            });
      const value =
        editor === "schema"
          ? "draft schema"
          : editor === "metadata"
            ? "Draft name"
            : "https://draft.example.com/token";
      fireEvent.change(input, { target: { value } });
      await user.keyboard("{Escape}");
      expect(mockReplace).not.toHaveBeenCalled();
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
      expect(screen.getByText("Discard unsaved changes?")).toBeVisible();
      expect(screen.getByRole("dialog")).toHaveAccessibleName(
        "Discard unsaved changes?"
      );
      await user.click(screen.getByRole("button", { name: "Cancel" }));
      expect(input).toHaveValue(value);
      await user.click(screen.getByRole("button", { name: "Close" }));
      await user.click(screen.getByRole("button", { name: "Discard changes" }));
      expect(mockReplace).toHaveBeenCalledWith("/admin/plugins", {
        scroll: false,
      });
    }
  );

  test("rejects an OAuth draft when its saved configuration link changes before save", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit authentication"));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Token URL" })).toHaveValue(
        "https://identity.example.com/token"
      )
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Token URL" }), {
      target: { value: "https://draft.example.com/token" },
    });
    tool = { ...tool, oauth_config_id: 8 };
    configs.add(8);
    const loading = deferred<Response>();
    oauthResponse = () => loading.promise;
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "Token URL" })
      ).not.toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeDisabled();
    expect(writes).toEqual([]);
    await act(async () =>
      loading.resolve(
        json({
          id: 8,
          name: "Replacement OAuth",
          authorization_url: "https://replacement.example.com/authorize",
          token_url: "https://replacement.example.com/token",
          scopes: [],
          has_client_credentials: true,
        })
      )
    );
    expect(screen.getByRole("textbox", { name: "Token URL" })).toHaveValue(
      "https://replacement.example.com/token"
    );
    expect(writes).toEqual([]);
  });

  test("backdrop dismiss protects a draft retained in an inactive tab", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    fireEvent.change(await screen.findByRole("textbox", { name: "Name" }), {
      target: { value: "Draft name" },
    });
    await findToolsPreview();
    fireEvent.pointerDown(document.body);
    expect(await screen.findByText("Discard unsaved changes?")).toBeVisible();
    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(await findEditorTab("Edit"));
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Draft name"
    );
  });

  test("shows plugin details in a dialog and closes to the directory", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    const dialog = await screen.findByRole("dialog", { name: /Release API/ });
    expect(screen.getByRole("tab", { name: "Configuration" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(dialog).toHaveAccessibleDescription("Read release status");
    expect(screen.queryByText("listReleases")).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
    ).toBeVisible();
    expect(
      screen.queryByRole("tab", { name: "OpenAPI schema" })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("1 tool detected")).not.toBeInTheDocument();
    expect(screen.queryByText("listReleases")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Tools" }));
    expect(screen.getByRole("tab", { name: "Tools" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(await findToolsPreview()).toBeInTheDocument();
    const search = screen.getByRole("textbox", { name: "Search tools" });
    await user.type(search, "missing endpoint");
    expect(screen.queryByText("listReleases")).not.toBeInTheDocument();
    expect(screen.getByText("No tools found")).toBeVisible();
    await user.clear(search);
    expect(screen.getByText("listReleases")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(mockReplace).toHaveBeenCalledWith("/admin/plugins", {
      scroll: false,
    });
  });

  test("edits inline in one dialog and preserves drafts while switching tabs", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit"));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Release API"
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Draft release API" },
    });
    await findToolsPreview();
    await user.click(await findEditorTab("Edit"));
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Draft release API"
    );
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: "Edit" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit schema" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit authentication" })
    ).not.toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  test("opens legacy authentication configuration without stacking dialogs", async () => {
    mockQuery = new URLSearchParams("configure=authentication");
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await screen.findByRole("dialog", { name: /Release API/ });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "Authentication" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  test("keeps detail open after revoked authentication permission is restored", async () => {
    const user = setupUser();
    render(
      <>
        <OpenAPIPluginDetailPage toolId={42} />
        <BackgroundRefresh />
      </>
    );
    await user.click(await findEditorTab("Edit authentication"));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Token URL" })).toHaveValue(
        "https://identity.example.com/token"
      )
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Token URL" }), {
      target: { value: "https://identity.example.com/new-token" },
    });
    tool = { ...tool, permissions: { edit: true, authenticate: false } };
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    const detailDialog = await screen.findByRole("dialog", {
      name: /Release API/,
    });
    expect(
      screen.queryByRole("button", { name: "Edit authentication" })
    ).not.toBeInTheDocument();
    tool = { ...tool, permissions: configuredTool.permissions };
    fireEvent.click(screen.getByText("Refresh tools"));
    await user.click(await findEditorTab("Edit authentication"));
    expect(screen.getByRole("dialog")).toBe(detailDialog);
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Token URL" })).toBeEnabled()
    );
    expect(writes).toEqual([]);
  });
});

describe("background detail reads", () => {
  test.each(["metadata", "schema", "authentication"] as const)(
    "keeps the same %s editor and draft after a failed background read",
    async (editor) => {
      const onError = jest.fn();
      const user = setupUser();
      render(
        <>
          <OpenAPIPluginDetailPage toolId={42} />
          <BackgroundRefresh />
        </>,
        { swrConfig: { onError } }
      );
      await user.click(
        await findEditorTab(
          editor === "metadata"
            ? "Edit"
            : editor === "schema"
              ? "Edit schema"
              : "Edit authentication"
        )
      );
      const dialog = await screen.findByRole("dialog");
      if (editor === "authentication") {
        await waitFor(() =>
          expect(
            within(dialog).getByRole("textbox", { name: "Token URL" })
          ).toHaveValue("https://identity.example.com/token")
        );
      }
      const input =
        editor === "schema"
          ? within(dialog).getByRole("textbox", {
              name: /OpenAPI Schema Definition/,
            })
          : within(dialog).getByRole("textbox", {
              name: editor === "metadata" ? "Name" : "Token URL",
            });
      const draft =
        editor === "schema"
          ? JSON.stringify({
              ...definition,
              info: { ...definition.info, title: "Draft release API" },
            })
          : editor === "metadata"
            ? "Draft release API"
            : "https://identity.example.com/draft-token";
      fireEvent.change(input, { target: { value: draft } });
      expect(input).toHaveValue(draft);
      failNextAuthRefresh = true;
      fireEvent.click(screen.getByText("Refresh tools"));
      await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
      expect(screen.getByRole("dialog")).toBe(dialog);
      expect(input).toBeInTheDocument();
      expect(input).toHaveValue(draft);
      expect(screen.queryByText("Could not load this plugin")).toBeNull();
    }
  );

  test("shows a background read failure when the cached list has no selected tool", async () => {
    listResponse = async () => json([]);
    const onError = jest.fn();
    render(
      <>
        <OpenAPIPluginDetailPage toolId={42} />
        <BackgroundRefresh />
      </>,
      { swrConfig: { onError } }
    );
    expect(await screen.findByText("Plugin not found")).toBeVisible();
    failNextAuthRefresh = true;
    fireEvent.click(screen.getByText("Refresh tools"));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Could not load this plugin")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});

describe("permission-bearing detail reads", () => {
  test("shows tools and hides all write controls for unstamped records", async () => {
    tool = { ...tool, permissions: undefined };
    render(<OpenAPIPluginDetailPage toolId={42} />);
    expect(await findToolsPreview()).toBeInTheDocument();
    expect(screen.getByText("/releases")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit schema" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit authentication" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
      })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "More actions" })
    ).not.toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalledWith("/api/tool/42");
  });

  test("opens requested authentication once after the stamped tool loads and preserves other query parameters", async () => {
    mockQuery = new URLSearchParams("configure=authentication&source=create");
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await screen.findByRole("dialog");
    expect(screen.getByRole("tab", { name: "Authentication" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(mockReplace).toHaveBeenCalledWith(
      "/admin/plugins/openapi/42?source=create",
      { scroll: false }
    );
    expect(mockReplace).toHaveBeenCalledTimes(1);
  });

  test("does not open authentication from a query without the authenticate capability", async () => {
    tool = { ...tool, permissions: { edit: true, authenticate: false } };
    mockQuery = new URLSearchParams("configure=authentication");
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await findToolsPreview();
    expect(screen.getByRole("dialog", { name: /Release API/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Authentication" })).toHaveAttribute(
      "aria-selected",
      "false"
    );
    expect(writes).toEqual([]);
    expect(global.fetch).not.toHaveBeenCalledWith("/api/admin/oauth-config/7");
  });

  test("shows a missing-plugin state instead of requesting an unstamped detail", async () => {
    render(<OpenAPIPluginDetailPage toolId={99} />);
    expect(await screen.findByText("Plugin not found")).toBeInTheDocument();
    expect(writes).toEqual([]);
  });
});

describe.each(["metadata", "schema", "authentication"] as const)(
  "%s save permission refresh",
  (editor) => {
    test.each(["denied", "missing"] as const)(
      "restores a visible detail dialog after the fresh tool is %s",
      async (outcome) => {
        const user = setupUser();
        const initialRead = jest.fn(async () => json([tool]));
        listResponse = initialRead;
        render(
          <ToastProvider>
            <OpenAPIPluginDetailPage toolId={42} />
          </ToastProvider>
        );
        await user.click(
          await findEditorTab(
            editor === "metadata"
              ? "Edit"
              : editor === "schema"
                ? "Edit schema"
                : "Edit authentication"
          )
        );
        const editorDialog = await screen.findByRole("dialog");
        if (editor === "authentication") {
          await waitFor(() =>
            expect(
              within(editorDialog).getByRole("textbox", { name: "Token URL" })
            ).toHaveValue("https://identity.example.com/token")
          );
        }
        fireEvent.change(
          editor === "schema"
            ? within(editorDialog).getByRole("textbox", {
                name: /OpenAPI Schema Definition/,
              })
            : within(editorDialog).getByRole("textbox", {
                name: editor === "metadata" ? "Name" : "Token URL",
              }),
          {
            target: {
              value:
                editor === "schema"
                  ? JSON.stringify({
                      ...definition,
                      info: { ...definition.info, title: "Deployment API" },
                    })
                  : editor === "metadata"
                    ? "Deployment API"
                    : "https://identity.example.com/new-token",
            },
          }
        );
        if (outcome === "denied") {
          tool = {
            ...tool,
            permissions: {
              edit: editor === "authentication",
              authenticate: editor !== "authentication",
            },
          };
        }
        const freshRead = jest.fn(async () =>
          json(outcome === "missing" ? [] : [tool])
        );
        listResponse = freshRead;
        const submit = within(editorDialog).getByRole("button", {
          name: "Save Changes",
        });
        await waitFor(() => expect(submit).toBeEnabled());
        expect(freshRead).not.toHaveBeenCalled();
        await user.click(submit);
        const detailDialog = await screen.findByRole("dialog", {
          name: outcome === "missing" ? /Configuration/ : /Release API/,
        });
        expect(detailDialog).toBeVisible();
        expect(screen.getAllByRole("dialog")).toHaveLength(1);
        if (outcome !== "missing") expect(detailDialog).toBe(editorDialog);
        if (outcome !== "missing") await findToolsPreview();
        expect(
          within(detailDialog).getByText(
            outcome === "missing" ? "Plugin not found" : "listReleases"
          )
        ).toBeVisible();
        expect(
          await screen.findByText(
            editor === "authentication"
              ? "Only the action's creator or an admin can manage authentication"
              : "Failed to update OpenAPI action"
          )
        ).toBeVisible();
        expect(freshRead).toHaveBeenCalledTimes(1);
        expect(writes).toEqual([]);
        expect(tool.name).toBe("Release API");
      }
    );
  }
);

describe("focused edit workflows", () => {
  test.each([{ customHeaders: [] }, { customHeaders: null }])(
    "shows None for a saved plugin with $customHeaders headers and opens the same method",
    async ({ customHeaders }) => {
      tool = { ...tool, oauth_config_id: null };
      listResponse = async () =>
        json([{ ...tool, custom_headers: customHeaders }]);
      const user = setupUser();
      render(<OpenAPIPluginDetailPage toolId={42} />);
      await user.click(
        await screen.findByRole("tab", { name: "Authentication" })
      );
      expect(await screen.findByRole("combobox")).toHaveValue(
        "No authentication"
      );
      expect(
        screen.queryByRole("textbox", { name: "Authorization URL" })
      ).not.toBeInTheDocument();
      expect(writes).toEqual([]);
    }
  );

  test("can clear saved OAuth with None", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit authentication"));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Token URL" })).toHaveValue(
        "https://identity.example.com/token"
      )
    );
    await user.click(screen.getByRole("combobox"));
    fireEvent.click(
      await screen.findByRole("option", { name: "No authentication" })
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save Changes" })
      ).toBeDisabled()
    );
    expect(tool.oauth_config_id).toBeNull();
    expect(configs.has(7)).toBe(false);
    expect(writes).toContainEqual({
      path: "/api/admin/tool/custom/42",
      method: "PUT",
      body: {
        custom_headers: [],
        passthrough_auth: false,
        oauth_config_id: null,
      },
    });
  });

  test("retries a failed OAuth link with its one acknowledged configuration", async () => {
    tool = { ...tool, oauth_config_id: null };
    failNextLink = true;
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit authentication"));
    if (!screen.queryByRole("textbox", { name: "Authorization URL" })) {
      await user.click(await screen.findByRole("combobox"));
      await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    }
    fireEvent.change(
      await screen.findByRole("textbox", { name: "Authorization URL" }),
      {
        target: { value: "https://identity.example.com/authorize" },
      }
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Token URL" }), {
      target: { value: "https://identity.example.com/token" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /OAuth Client ID/ }), {
      target: { value: "release-client" },
    });
    fireEvent.change(screen.getByLabelText(/OAuth Client Secret/), {
      target: { value: "release-secret" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText(/Link failed/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save Changes" })
      ).toBeDisabled()
    );
    expect(configCreates).toBe(1);
    expect(tool.oauth_config_id).toBe(99);
    expect(writes).toContainEqual({
      path: "/api/admin/oauth-config/99",
      method: "PUT",
      body: {
        authorization_url: "https://identity.example.com/authorize",
        token_url: "https://identity.example.com/token",
        client_id: "release-client",
        client_secret: "release-secret",
        scopes: [],
        supports_pkce: false,
      },
    });
  });

  test.each(["new credentials", "masked credentials"])(
    "a successful switch to headers followed by refresh failure never reuses the deleted OAuth ID with %s",
    async (credentials) => {
      const user = setupUser();
      render(<OpenAPIPluginDetailPage toolId={42} />);
      await user.click(await findEditorTab("Edit authentication"));
      await waitFor(() =>
        expect(screen.getByRole("textbox", { name: "Token URL" })).toHaveValue(
          "https://identity.example.com/token"
        )
      );
      await user.click(screen.getByRole("combobox"));
      await user.keyboard(
        "{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}"
      );
      fireEvent.change(screen.getByRole("textbox", { name: "Value 1" }), {
        target: { value: "release-key" },
      });
      failRefreshAfterWrite = true;
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Save Changes" })
        ).toBeEnabled()
      );
      await user.click(screen.getByRole("button", { name: "Save Changes" }));
      expect(
        await screen.findByText("An error occurred while fetching the data.")
      ).toBeVisible();
      expect(configs.has(7)).toBe(false);
      expect(screen.getByRole("textbox", { name: "Value 1" })).toHaveValue(
        "release-key"
      );
      await user.click(screen.getByRole("combobox"));
      await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
      if (credentials === "masked credentials") {
        await waitFor(() =>
          expect(
            screen.getByRole("button", { name: "Save Changes" })
          ).toBeEnabled()
        );
        await user.click(screen.getByRole("button", { name: "Save Changes" }));
        expect(configCreates).toBe(0);
        expect(screen.getByRole("dialog")).toBeVisible();
        expect(tool.oauth_config_id).toBeNull();
      }
      fireEvent.change(
        screen.getByRole("textbox", { name: /OAuth Client ID/ }),
        {
          target: { value: "new-client" },
        }
      );
      fireEvent.change(screen.getByLabelText(/OAuth Client Secret/), {
        target: { value: "new-secret" },
      });
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Save Changes" })
        ).toBeEnabled()
      );
      await user.click(screen.getByRole("button", { name: "Save Changes" }));
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Save Changes" })
        ).toBeDisabled()
      );
      expect(tool.oauth_config_id).toBe(99);
      expect(configCreates).toBe(1);
      expect(configs).toEqual(new Set([99]));
      expect(
        writes.filter((write) => write.path === "/api/admin/oauth-config/7")
      ).toEqual([]);
    }
  );

  test("None clears saved headers after a failed OAuth link and keeps the unlinked ID available for another retry", async () => {
    tool = {
      ...tool,
      oauth_config_id: null,
      custom_headers: [{ key: "Authorization", value: "release-key" }],
    };
    failNextLink = true;
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit authentication"));
    await user.click(await screen.findByRole("combobox"));
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    fireEvent.change(
      screen.getByRole("textbox", { name: "Authorization URL" }),
      {
        target: { value: "https://identity.example.com/authorize" },
      }
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Token URL" }), {
      target: { value: "https://identity.example.com/token" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /OAuth Client ID/ }), {
      target: { value: "release-client" },
    });
    fireEvent.change(screen.getByLabelText(/OAuth Client Secret/), {
      target: { value: "release-secret" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText(/Link failed/)).toBeVisible();
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{ArrowDown}{Enter}");
    failRefreshAfterWrite = true;
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(
      await screen.findByText("An error occurred while fetching the data.")
    ).toBeVisible();
    expect(tool).toEqual(
      expect.objectContaining({
        oauth_config_id: null,
        custom_headers: [],
        passthrough_auth: false,
      })
    );
    expect(configs.has(99)).toBe(true);
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save Changes" })
      ).toBeDisabled()
    );
    expect(tool.oauth_config_id).toBe(99);
    expect(configCreates).toBe(1);
  });

  test("preserves OAuth on metadata saves and waits for stamped list revalidation", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit"));
    const dialog = screen.getByRole("dialog");
    await user.clear(within(dialog).getByRole("textbox", { name: "Name" }));
    await user.type(
      within(dialog).getByRole("textbox", { name: "Name" }),
      "Deployment API"
    );
    const reload = deferred<Response>();
    listResponse = () =>
      writes.length ? reload.promise : Promise.resolve(json([tool]));
    await user.click(
      within(dialog).getByRole("button", { name: "Save Changes" })
    );
    await waitFor(() =>
      expect(writes).toContainEqual({
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: {
          name: "Deployment API",
          description: "Read release status",
          oauth_config_id: 7,
        },
      })
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Saving..." })
    ).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(mockReplace).not.toHaveBeenCalled();
    expect(
      screen.queryByText("Discard unsaved changes?")
    ).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Saving..." }));
    expect(
      writes.filter((write) => write.path === "/api/admin/tool/custom/42")
    ).toHaveLength(1);
    await act(async () => {
      reload.resolve(
        json([{ ...tool, name: "Deployment API", permissions: {} }])
      );
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Save Changes" })
      ).not.toBeInTheDocument()
    );
    expect(
      screen.queryByRole("button", { name: "Edit" })
    ).not.toBeInTheDocument();
  });

  test("metadata uses the fresh OAuth link without changing other authentication fields", async () => {
    tool = { ...tool, oauth_config_id: 99 };
    configs = new Set([99, 100]);
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit"));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Deployment API" },
    });
    tool = {
      ...tool,
      oauth_config_id: 100,
      custom_headers: [{ key: "X-Release-Key", value: "current-key" }],
      passthrough_auth: true,
    };
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save Changes" })
      ).toBeDisabled()
    );
    expect(writes).toEqual([
      {
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: {
          name: "Deployment API",
          description: "Read release status",
          oauth_config_id: 100,
        },
      },
    ]);
    expect(tool).toEqual(
      expect.objectContaining({
        name: "Deployment API",
        oauth_config_id: 100,
        custom_headers: [{ key: "X-Release-Key", value: "current-key" }],
        passthrough_auth: true,
      })
    );
    expect(configs.has(100)).toBe(true);
  });

  test("does not write metadata when the fresh tool no longer permits editing", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit"));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Deployment API" },
    });
    tool = { ...tool, permissions: { edit: false, authenticate: true } };
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Edit" })).toBeNull()
    );
    expect(await findToolsPreview()).toBeVisible();
    expect(tool.name).toBe("Release API");
    expect(writes).toEqual([]);
  });

  test("preserves authentication when editing the reused schema form", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit schema"));
    const dialog = await screen.findByRole("dialog");
    const updatedDefinition = {
      ...definition,
      info: { ...definition.info, description: "Updated release status" },
    };
    fireEvent.change(
      within(dialog).getByRole("textbox", {
        name: /OpenAPI Schema Definition/,
      }),
      {
        target: {
          value: JSON.stringify(updatedDefinition),
        },
      }
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Save Changes" })
    );
    await waitFor(() =>
      expect(writes).toContainEqual({
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: {
          definition: updatedDefinition,
          name: "Release API",
          oauth_config_id: 7,
          description: "Read release status",
        },
      })
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save Changes" })
      ).toBeDisabled()
    );
  });

  test("keeps masked OAuth credentials unchanged on authentication saves", async () => {
    const user = setupUser();
    render(<OpenAPIPluginDetailPage toolId={42} />);
    await user.click(await findEditorTab("Edit authentication"));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(
        within(dialog).getByRole("textbox", { name: "Token URL" })
      ).toHaveValue("https://identity.example.com/token")
    );
    const tokenUrl = within(dialog).getByRole("textbox", {
      name: "Token URL",
    });
    await user.clear(tokenUrl);
    await user.type(tokenUrl, "https://identity.example.com/new-token");
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Save Changes" })
      ).toBeEnabled()
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Save Changes" })
    );
    await waitFor(() =>
      expect(writes).toContainEqual({
        path: "/api/admin/oauth-config/7",
        method: "PUT",
        body: {
          authorization_url: "https://identity.example.com/authorize",
          token_url: "https://identity.example.com/new-token",
          scopes: ["read"],
          supports_pkce: false,
        },
      })
    );
    expect(writes).toContainEqual({
      path: "/api/admin/tool/custom/42",
      method: "PUT",
      body: { custom_headers: [], passthrough_auth: false, oauth_config_id: 7 },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save Changes" })
      ).toBeDisabled()
    );
  });
});

test("keeps lifecycle controls on the Plugins directory, not detail", async () => {
  render(<OpenAPIPluginDetailPage toolId={42} />);
  await findEditorTab("Edit schema");
  expect(
    screen.queryByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Enable" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete" })
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(writes).toEqual([]);
});
