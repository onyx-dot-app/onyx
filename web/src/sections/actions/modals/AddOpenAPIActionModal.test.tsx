import { type ComponentProps } from "react";
import { Modal } from "@opal/components";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
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
import type { MethodSpec } from "@/lib/tools/types";

type SchemaModalProps = Partial<ComponentProps<typeof AddOpenAPIActionModal>>;

function SchemaModal(props: SchemaModalProps) {
  return (
    <Modal open>
      <PluginModalContent>
        <AddOpenAPIActionModal
          title="Add OpenAPI plugin"
          onClose={jest.fn()}
          onBusyChange={jest.fn()}
          onConfigureAuthentication={jest.fn()}
          {...props}
        />
      </PluginModalContent>
    </Modal>
  );
}

async function renderSchemaModal(props: SchemaModalProps = {}) {
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

function mockSchemaFetch() {
  return jest.spyOn(global, "fetch");
}

afterEach(() => jest.restoreAllMocks());

describe("schema validation request ownership", () => {
  test("shows descriptions without a server preview", async () => {
    mockSchemaFetch().mockImplementation(
      async () => new Response(JSON.stringify({ methods: methods("getUser") }))
    );
    await renderSchemaModal();
    fireEvent.change(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      {
        target: { value: JSON.stringify(definition("GitHub")) },
      }
    );
    expect(screen.queryByText("GitHub")).not.toBeInTheDocument();
    expect(
      screen.queryByText("https://github.example.com")
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: /Description for Humans/ })
    ).toHaveValue("");
    expect(
      screen.getByRole("textbox", { name: /Description for Agents/ })
    ).toHaveValue("GitHub description");
    expect(screen.getAllByRole("textbox")).toEqual([
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      screen.getByRole("textbox", { name: /Description for Humans/ }),
      screen.getByRole("textbox", { name: /Description for Agents/ }),
    ]);
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
    fireEvent.change(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      { target: { value: raw } }
    );
    await setupUser().click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(onNext).toHaveBeenCalledWith({
        name: "True",
        description: "",
        definition: schema,
      })
    );
  });

  test.each(["success", "error"])(
    "keeps the current validation state when an older check returns %s",
    async (olderResult) => {
      const older = deferred<Response>();
      const current = deferred<Response>();
      const fetchSpy = mockSchemaFetch()
        .mockReturnValueOnce(older.promise)
        .mockReturnValueOnce(current.promise);
      await renderSchemaModal({ initialDefinition: definition("Saved") });
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      fireEvent.change(
        screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
        {
          target: { value: JSON.stringify(definition("Current")) },
        }
      );
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      await act(async () => {
        current.resolve(
          new Response(JSON.stringify({ methods: methods("current") }))
        );
      });
      expect(screen.queryByText("Older schema failed")).not.toBeInTheDocument();
      await act(async () => {
        older.resolve(
          olderResult === "success"
            ? new Response(JSON.stringify({ methods: methods("older") }))
            : new Response(JSON.stringify({ detail: "Older schema failed" }), {
                status: 400,
              })
        );
      });
      expect(screen.queryByText("older")).not.toBeInTheDocument();
      expect(screen.queryByText("Older schema failed")).not.toBeInTheDocument();
      expect(
        screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
      ).toHaveValue(JSON.stringify(definition("Current")));
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
    fireEvent.change(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      {
        target: { value: JSON.stringify(definition("Current")) },
      }
    );
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

  test("ignores a validation response after clearing the field", async () => {
    const pending = deferred<Response>();
    const fetchSpy = mockSchemaFetch().mockReturnValue(pending.promise);
    await renderSchemaModal({ initialDefinition: definition("Older") });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    fireEvent.change(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      { target: { value: "" } }
    );
    await act(async () => {
      pending.resolve(
        new Response(JSON.stringify({ methods: methods("older") }))
      );
    });
    expect(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
    ).toHaveValue("");
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
    fireEvent.change(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      {
        target: { value: rawDefinition },
      }
    );
    const format = screen.getByRole("button", { name: "Format definition" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(format);
    expect(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
    ).toHaveValue(rawDefinition);
    expect(format).toBeDisabled();
    expect(format).toHaveAccessibleName("Format definition");
    await act(async () => {
      pending.resolve(new Response(JSON.stringify({ methods: [] })));
    });
    await waitFor(() =>
      expect(onConfigureAuthentication).toHaveBeenCalledWith({
        name: "Checking",
        description: "",
        definition: definition("Checking"),
      })
    );
    expect(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
    ).toBeEnabled();
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
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("preview")).not.toBeInTheDocument();
    const rawDefinition = JSON.stringify(definition("Draft")).replace(
      /}$/,
      ",}"
    );
    await act(async () => {
      fireEvent.change(
        screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
        {
          target: { value: rawDefinition },
        }
      );
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
        description: "",
        definition: definition("Draft"),
      })
    );
    expect(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
    ).toHaveValue(rawDefinition);
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
    expect(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
    ).toHaveValue("");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  test("shows the existing JSON error for an invalid draft", async () => {
    mockSchemaFetch();
    await renderSchemaModal();
    fireEvent.change(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ }),
      {
        target: { value: "{invalid" },
      }
    );
    expect(await screen.findByText("Invalid JSON format")).toBeVisible();
    expect(
      screen.getByRole("textbox", { name: /OpenAPI Schema Definition/ })
    ).toHaveValue("{invalid");
  });
});

test("human descriptions stay separate while agent descriptions sync with the schema", async () => {
  mockSchemaFetch().mockResolvedValue(
    new Response(JSON.stringify({ methods: [] }))
  );
  const onConfigureAuthentication = jest.fn();
  await renderSchemaModal({
    initialDefinition: definition("Draft"),
    onConfigureAuthentication,
  });
  const human = screen.getByRole("textbox", { name: /Description for Humans/ });
  const agent = screen.getByRole("textbox", { name: /Description for Agents/ });
  const schema = screen.getByRole("textbox", {
    name: /OpenAPI Schema Definition/,
  });
  expect(human).toHaveValue("");
  expect(agent).toHaveValue("Draft description");
  fireEvent.change(human, { target: { value: "Display summary" } });
  fireEvent.change(agent, { target: { value: "Agent instructions" } });
  const updated = {
    ...definition("Draft"),
    info: { ...definition("Draft").info, description: "Agent instructions" },
  };
  expect(schema).toHaveValue(JSON.stringify(updated, null, 2));
  expect(human).toHaveValue("Display summary");
  const fromSchema = {
    ...updated,
    info: { ...updated.info, description: "Edited in JSON" },
  };
  fireEvent.change(schema, { target: { value: JSON.stringify(fromSchema) } });
  expect(agent).toHaveValue("Edited in JSON");
  fireEvent.change(schema, { target: { value: "{invalid" } });
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: /Description for Agents/ })
    ).toBeDisabled()
  );
  expect(human).toHaveValue("Display summary");
  fireEvent.change(schema, { target: { value: JSON.stringify(fromSchema) } });
  await setupUser().click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() =>
    expect(onConfigureAuthentication).toHaveBeenCalledWith({
      name: "Draft",
      description: "Display summary",
      definition: fromSchema,
    })
  );
});
