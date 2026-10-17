import { useEffect, type ComponentProps } from "react";
import { useCreateModal } from "@opal/components";
import { toast } from "@opal/layouts";
import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import type { MethodSpec, ToolSnapshot } from "@/lib/tools/types";

function SchemaModal({
  open = true,
  ...props
}: ComponentProps<typeof AddOpenAPIActionModal> & { open?: boolean }) {
  const modal = useCreateModal();
  useEffect(() => modal.toggle(open), [modal.toggle, open]);
  return (
    <modal.Provider>
      <AddOpenAPIActionModal {...props} />
    </modal.Provider>
  );
}

function CachedSchemaModal(props: ComponentProps<typeof SchemaModal>) {
  const { openApiTools } = useOpenApiTools();
  const existingTool = openApiTools?.find((candidate) => candidate.id === 42);
  return existingTool ? (
    <SchemaModal {...props} existingTool={existingTool} />
  ) : null;
}

async function renderSchemaModal(
  props: ComponentProps<typeof AddOpenAPIActionModal> = {}
) {
  const view = render(<SchemaModal {...props} />);
  await act(async () => undefined);
  return view;
}

function definition(title: string) {
  return {
    openapi: "3.0.0",
    info: { title, description: `${title} description`, version: "1.0" },
    servers: [{ url: `https://${title.toLowerCase()}.example.com` }],
    paths: {},
  };
}

function methods(name: string): MethodSpec[] {
  return [
    {
      name,
      summary: `${name} summary`,
      method: "GET",
      path: `/${name}`,
      spec: {},
      custom_headers: [],
    },
  ];
}

const tool: ToolSnapshot = {
  id: 42,
  name: "Saved",
  display_name: "Saved",
  description: "Saved description",
  definition: definition("Saved"),
  custom_headers: [{ key: "X-Api-Key", value: "saved-key" }],
  in_code_tool_id: null,
  passthrough_auth: false,
  oauth_config_id: 99,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: true,
  permissions: { edit: true, authenticate: true },
};

function mockSchemaFetch() {
  const requests = jest.fn<
    ReturnType<typeof fetch>,
    Parameters<typeof fetch>
  >();
  jest.spyOn(global, "fetch").mockImplementation((input, init) => {
    if (String(input) === "/api/tool/openapi")
      return Promise.resolve(new Response(JSON.stringify([tool])));
    return requests(input, init);
  });
  return requests;
}

afterEach(() => jest.restoreAllMocks());

describe("inline schema editing", () => {
  test("saves through the parent footer without a modal provider or closing", async () => {
    const user = setupUser();
    const onUpdate = jest.fn();
    const onClose = jest.fn();
    const onBusyChange = jest.fn();
    const onViewTools = jest.fn();
    const updateResponse = deferred<Response>();
    mockSchemaFetch().mockImplementation(async (input, init) => {
      if (String(input) === "/api/admin/tool/custom/validate")
        return new Response(JSON.stringify({ methods: methods("getUser") }));
      if (
        String(input) === "/api/admin/tool/custom/42" &&
        init?.method === "PUT"
      )
        return updateResponse.promise;
      throw new Error(`Unexpected request to ${String(input)}`);
    });
    const footer = document.createElement("div");
    document.body.appendChild(footer);
    const view = render(
      <AddOpenAPIActionModal
        presentation="inline"
        footerTarget={footer}
        existingTool={tool}
        onUpdate={onUpdate}
        onClose={onClose}
        onBusyChange={onBusyChange}
        onViewTools={onViewTools}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved description")).not.toBeInTheDocument();
    expect(await screen.findByText("1 tool detected")).toBeVisible();
    expect(screen.queryByText("getUser")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View tools" }));
    expect(onViewTools).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: JSON.stringify(definition("Updated")) },
    });
    const save = screen.getByRole("button", { name: "Save Changes" });
    await screen.findByText("1 tool detected");
    expect(screen.getByRole("button", { name: "View tools" })).toBeDisabled();
    await user.hover(screen.getByRole("button", { name: "View tools" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Save changes to update tools."
    );
    await user.unhover(screen.getByRole("button", { name: "View tools" }));
    expect(footer).toContainElement(save);
    await user.click(save);
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(true));
    const editor = screen.getByRole("textbox");
    expect(editor).toBeDisabled();
    await user.type(editor, " later edits");
    expect(editor).toHaveValue(JSON.stringify(definition("Updated")));
    await act(async () => {
      updateResponse.resolve(
        new Response(
          JSON.stringify({ ...tool, definition: definition("Updated") })
        )
      );
    });
    await waitFor(() => expect(onUpdate).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox")).toHaveValue(
      JSON.stringify(definition("Updated"))
    );
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeDisabled();
    expect(onBusyChange).toHaveBeenLastCalledWith(false);
    expect(editor).toBeEnabled();
    view.rerender(
      <AddOpenAPIActionModal
        presentation="inline"
        footerTarget={footer}
        existingTool={tool}
        active={false}
      />
    );
    expect(footer).toBeEmptyDOMElement();
    view.unmount();
    footer.remove();
  });
});

describe("schema preview request ownership", () => {
  test("shows the parsed plugin identity and server URL once during creation", async () => {
    mockSchemaFetch().mockImplementation(
      async () => new Response(JSON.stringify({ methods: methods("getUser") }))
    );
    await renderSchemaModal();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: JSON.stringify(definition("GitHub")) },
    });
    expect(await screen.findByText("GitHub")).toBeVisible();
    expect(screen.getAllByText("https://github.example.com")).toHaveLength(1);
    expect(screen.getByText("GitHub description")).toBeVisible();
    expect(
      screen.queryByText(
        "URL found in the schema. Only connect to servers you trust."
      )
    ).not.toBeInTheDocument();
  });
  test("lenient JSON parsing preserves quoted literals and punctuation", async () => {
    const schema = {
      ...definition("True"),
      info: { title: "True", description: 'False,} "None"', version: "1.0" },
      servers: [{ url: "https://None.example.com/False" }],
      "x-enabled": true,
      "x-disabled": false,
      "x-null": null,
      "x-values": [true, false, null],
    };
    const raw = JSON.stringify(schema)
      .replace('"x-enabled":true', '"x-enabled":True')
      .replace('"x-disabled":false', '"x-disabled":False')
      .replace('"x-null":null', '"x-null":None')
      .replace('"x-values":[true,false,null]', '"x-values":[True,False,None,]')
      .replace(/}$/, ",}");
    const onNext = jest.fn();
    mockSchemaFetch().mockImplementation(
      async () => new Response(JSON.stringify({ methods: [] }))
    );
    await renderSchemaModal({ onConfigureAuthentication: onNext });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: raw } });
    await setupUser().click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(onNext).toHaveBeenCalledWith({
        name: "True",
        description: 'False,} "None"',
        definition: schema,
        custom_headers: [],
        passthrough_auth: false,
      })
    );
  });

  test.each(["success", "error"])(
    "keeps the current preview when an older check returns %s",
    async (olderResult) => {
      const older = deferred<Response>();
      const current = deferred<Response>();
      const fetchSpy = mockSchemaFetch()
        .mockReturnValueOnce(older.promise)
        .mockReturnValueOnce(current.promise);
      await renderSchemaModal({ existingTool: tool });
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      fireEvent.change(screen.getByRole("textbox"), {
        target: { value: JSON.stringify(definition("Current")) },
      });
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      await act(async () => {
        current.resolve(
          new Response(JSON.stringify({ methods: methods("current") }))
        );
      });
      expect(screen.getByText("current")).toBeVisible();
      expect(screen.getAllByText("Current")[0]).toBeVisible();
      await act(async () => {
        older.resolve(
          olderResult === "success"
            ? new Response(JSON.stringify({ methods: methods("older") }))
            : new Response(JSON.stringify({ detail: "Older schema failed" }), {
                status: 400,
              })
        );
      });
      expect(screen.getByText("current")).toBeVisible();
      expect(screen.getAllByText("Current description")[0]).toBeVisible();
      expect(
        screen.getAllByText("https://current.example.com")[0]
      ).toBeVisible();
      expect(screen.queryByText("older")).not.toBeInTheDocument();
      expect(screen.queryByText("Older schema failed")).not.toBeInTheDocument();
      expect(screen.getByRole("textbox")).toHaveValue(
        JSON.stringify(definition("Current"))
      );
    }
  );

  test("keeps the current validation error when an older check succeeds", async () => {
    const older = deferred<Response>();
    const current = deferred<Response>();
    const fetchSpy = mockSchemaFetch()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(current.promise);
    await renderSchemaModal({ initialDefinition: definition("Older") });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: JSON.stringify(definition("Current")) },
    });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    await act(async () => {
      current.resolve(
        new Response(JSON.stringify({ detail: "Current schema failed" }), {
          status: 400,
        })
      );
    });
    expect(screen.getByText("Current schema failed")).toBeVisible();
    await act(async () => {
      older.resolve(
        new Response(JSON.stringify({ methods: methods("older") }))
      );
    });
    expect(screen.getByText("Current schema failed")).toBeVisible();
    expect(screen.queryByText("older")).not.toBeInTheDocument();
  });

  test("clears the preview immediately and ignores a response after clearing the field", async () => {
    const pending = deferred<Response>();
    const fetchSpy = mockSchemaFetch().mockReturnValue(pending.promise);
    await renderSchemaModal({ initialDefinition: definition("Older") });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    await act(async () => {
      pending.resolve(
        new Response(JSON.stringify({ methods: methods("older") }))
      );
    });
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(screen.queryByText("older")).not.toBeInTheDocument();
  });
});

describe("explicit schema validation", () => {
  test("keeps Format disabled until the explicit Continue check finishes", async () => {
    const user = setupUser();
    const pending = deferred<Response>();
    const onConfigureAuthentication = jest.fn();
    mockSchemaFetch().mockReturnValue(pending.promise);
    await renderSchemaModal({ onConfigureAuthentication });
    const rawDefinition = JSON.stringify(definition("Checking"));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: rawDefinition },
    });
    const format = screen.getByRole("button", { name: "Format definition" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(format);
    expect(screen.getByRole("textbox")).toHaveValue(rawDefinition);
    expect(format).toBeDisabled();
    expect(format).toHaveAccessibleName("Format definition");
    await act(async () => {
      pending.resolve(new Response(JSON.stringify({ methods: [] })));
    });
    await waitFor(() =>
      expect(onConfigureAuthentication).toHaveBeenCalledWith({
        name: "Checking",
        description: "Checking description",
        definition: definition("Checking"),
        custom_headers: [],
        passthrough_auth: false,
      })
    );
    expect(screen.getByRole("textbox")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  test("validates Continue again and preserves a schema draft with trailing commas", async () => {
    const user = setupUser();
    const onConfigureAuthentication = jest.fn();
    const explicit = deferred<Response>();
    const fetchSpy = mockSchemaFetch()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ methods: methods("preview") }))
      )
      .mockReturnValueOnce(explicit.promise);
    await renderSchemaModal({
      initialDefinition: definition("Preview"),
      onConfigureAuthentication,
    });
    expect(await screen.findByText("preview")).toBeVisible();
    const rawDefinition = JSON.stringify(definition("Draft")).replace(
      /}$/,
      ",}"
    );
    await act(async () => {
      fireEvent.change(screen.getByRole("textbox"), {
        target: { value: rawDefinition },
      });
    });
    expect(screen.queryByText("preview")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      screen.getByRole("button", { name: /^Checking server/ })
    ).toBeDisabled();
    expect(onConfigureAuthentication).not.toHaveBeenCalled();
    expect(fetchSpy).toHaveBeenLastCalledWith(
      "/api/admin/tool/custom/validate",
      expect.objectContaining({
        body: JSON.stringify({ definition: definition("Draft") }),
      })
    );
    await act(async () => {
      explicit.resolve(
        new Response(JSON.stringify({ methods: methods("checked") }))
      );
    });
    await waitFor(() =>
      expect(onConfigureAuthentication).toHaveBeenCalledWith({
        name: "Draft",
        description: "Draft description",
        definition: definition("Draft"),
        custom_headers: [],
        passthrough_auth: false,
      })
    );
    expect(screen.getByRole("textbox")).toHaveValue(rawDefinition);
  });

  test("does not advance an unmounted form after its Continue check completes", async () => {
    const user = setupUser();
    const pending = deferred<Response>();
    const onConfigureAuthentication = jest.fn();
    mockSchemaFetch().mockReturnValue(pending.promise);
    const view = await renderSchemaModal({
      initialDefinition: definition("Closed"),
      onConfigureAuthentication,
    });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      screen.getByRole("button", { name: /^Checking server/ })
    ).toBeDisabled();
    view.unmount();
    await act(async () => {
      pending.resolve(
        new Response(JSON.stringify({ methods: methods("closed") }))
      );
    });
    expect(onConfigureAuthentication).not.toHaveBeenCalled();
    await renderSchemaModal();
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  test("shows the existing JSON error for an invalid draft", async () => {
    mockSchemaFetch();
    await renderSchemaModal();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "{invalid" },
    });
    expect(await screen.findByText("Invalid JSON format")).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveValue("{invalid");
  });
});

describe("schema edit contracts", () => {
  test("keeps the exact draft after refreshing a changed saved schema and retrying a failed update", async () => {
    const user = setupUser();
    const onUpdate = jest.fn();
    const showError = jest
      .spyOn(toast, "error")
      .mockImplementation(() => "error-toast");
    let savedTool = tool;
    const updates = jest
      .fn<ReturnType<typeof fetch>, Parameters<typeof fetch>>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Schema save failed" }), {
          status: 500,
        })
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ ...tool, definition: definition("My draft") })
        )
      );
    jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      if (String(input) === "/api/tool/openapi")
        return new Response(JSON.stringify([savedTool]));
      if (String(input) === "/api/admin/tool/custom/validate")
        return new Response(JSON.stringify({ methods: [] }));
      if (
        String(input) === "/api/admin/tool/custom/42" &&
        init?.method === "PUT"
      )
        return updates(input, init);
      throw new Error(`Unexpected request to ${String(input)}`);
    });
    render(<CachedSchemaModal onUpdate={onUpdate} />);
    const input = await screen.findByRole("textbox");
    expect(input).toHaveValue(JSON.stringify(tool.definition, null, 2));
    const rawDefinition = `\n${JSON.stringify(definition("My draft"), null, 3).replace(/}$/, ",}")}\n`;
    await user.clear(input);
    await user.paste(rawDefinition);
    savedTool = {
      ...tool,
      definition: definition("Server revision"),
      oauth_config_id: 100,
      oauth_config_name: "Latest account",
    };
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith(
        "Failed to update tool: Schema save failed"
      )
    );
    expect(screen.getByRole("textbox")).toHaveValue(rawDefinition);
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled();
    expect(onUpdate).not.toHaveBeenCalled();
    savedTool = { ...savedTool, oauth_config_id: 101 };
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ definition: definition("My draft") })
      )
    );
    expect(updates).toHaveBeenCalledTimes(2);
    for (const [index, oauthConfigId] of [100, 101].entries()) {
      expect(updates).toHaveBeenNthCalledWith(
        index + 1,
        "/api/admin/tool/custom/42",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            definition: definition("My draft"),
            oauth_config_id: oauthConfigId,
            name: "My draft",
            description: "My draft description",
          }),
        })
      );
    }
  });

  test("loads the current saved schema after closing and reopening the editor", async () => {
    mockSchemaFetch().mockResolvedValue(
      new Response(JSON.stringify({ methods: [] }))
    );
    const view = await renderSchemaModal({ existingTool: tool });
    expect(screen.getByRole("textbox")).toHaveValue(
      JSON.stringify(tool.definition, null, 2)
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: JSON.stringify(definition("Discarded draft")) },
    });
    view.rerender(<SchemaModal open={false} existingTool={tool} />);
    await waitFor(() =>
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    );
    const currentTool = { ...tool, definition: definition("Current saved") };
    view.rerender(<SchemaModal open existingTool={currentTool} />);
    expect(await screen.findByRole("textbox")).toHaveValue(
      JSON.stringify(currentTool.definition, null, 2)
    );
  });

  test("preserves fresh authentication when saving a cached schema editor", async () => {
    const user = setupUser();
    const onUpdate = jest.fn();
    const updateResponse = deferred<Response>();
    const freshTool = {
      ...tool,
      oauth_config_id: 100,
      custom_headers: [{ key: "X-Api-Key", value: "fresh-key" }],
      passthrough_auth: true,
    };
    let savedTool: ToolSnapshot = tool;
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input, init) => {
        if (String(input) === "/api/admin/tool/custom/validate")
          return new Response(JSON.stringify({ methods: [] }));
        if (String(input) === "/api/tool/openapi")
          return new Response(JSON.stringify([savedTool]));
        if (
          String(input) === "/api/admin/tool/custom/42" &&
          init?.method === "PUT"
        ) {
          savedTool = { ...savedTool, ...JSON.parse(String(init.body)) };
          return updateResponse.promise;
        }
        throw new Error(`Unexpected request to ${String(input)}`);
      });
    await renderSchemaModal({ existingTool: tool, onUpdate });
    savedTool = freshTool;
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: JSON.stringify(definition("Edited")) },
    });
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/tool/custom/42",
        expect.objectContaining({ method: "PUT" })
      )
    );
    const format = screen.getByRole("button", { name: "Format definition" });
    expect(format).toBeDisabled();
    await user.click(format);
    expect(screen.getByRole("textbox")).toHaveValue(
      JSON.stringify(definition("Edited"))
    );
    await act(async () => {
      updateResponse.resolve(new Response(JSON.stringify(savedTool)));
    });
    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ id: 42, definition: definition("Edited") })
      )
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/tool/custom/42",
      expect.objectContaining({
        body: JSON.stringify({
          definition: definition("Edited"),
          oauth_config_id: 100,
          name: "Edited",
          description: "Edited description",
        }),
      })
    );
    expect(savedTool.oauth_config_id).toBe(100);
    expect(savedTool.custom_headers).toEqual([
      { key: "X-Api-Key", value: "fresh-key" },
    ]);
    expect(savedTool.passthrough_auth).toBe(true);
    expect(
      fetchSpy.mock.calls.filter(
        ([input]) => String(input) === "/api/tool/openapi"
      )
    ).toHaveLength(2);
  });

  test("rejects a schema save when fresh edit permission has been revoked", async () => {
    const onUpdate = jest.fn();
    const showError = jest
      .spyOn(toast, "error")
      .mockImplementation(() => "error-toast");
    let freshTool = tool;
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input) => {
        if (String(input) === "/api/tool/openapi")
          return new Response(JSON.stringify([freshTool]));
        if (String(input) === "/api/admin/tool/custom/validate")
          return new Response(JSON.stringify({ methods: [] }));
        return new Response(
          JSON.stringify({ ...tool, definition: definition("Denied") })
        );
      });
    await renderSchemaModal({ existingTool: tool, onUpdate });
    freshTool = {
      ...tool,
      permissions: { edit: false, authenticate: true },
    };
    const rawDefinition = JSON.stringify(definition("Denied"));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: rawDefinition },
    });
    await setupUser().click(
      screen.getByRole("button", { name: "Save Changes" })
    );
    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith("Failed to update OpenAPI action")
    );
    expect(screen.getByRole("textbox")).toHaveValue(rawDefinition);
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled();
    expect(fetchSpy).not.toHaveBeenCalledWith(
      "/api/admin/tool/custom/42",
      expect.anything()
    );
    expect(onUpdate).not.toHaveBeenCalled();
    expect(
      fetchSpy.mock.calls.filter(
        ([input]) => String(input) === "/api/tool/openapi"
      )
    ).toHaveLength(2);
  });

  test("keeps schema edits disabled without stamped permissions", async () => {
    mockSchemaFetch().mockResolvedValue(
      new Response(JSON.stringify({ methods: [] }))
    );
    await renderSchemaModal({
      existingTool: {
        ...tool,
        permissions: { edit: false, authenticate: false },
      },
    });
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: JSON.stringify(definition("Denied")) },
    });
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeDisabled();
  });
});
