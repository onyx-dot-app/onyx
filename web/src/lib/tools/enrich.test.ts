import { enrichToolSnapshot, type RawToolSnapshot } from "@/lib/tools/enrich";

const raw: RawToolSnapshot = {
  id: 1,
  name: "",
  display_name: "",
  description: "",
  definition: {
    openapi: "3.0.0",
    info: { title: "Tasks API", description: "Create and list tasks." },
    paths: {},
  },
  custom_headers: null,
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
};

describe("enrichToolSnapshot", () => {
  test("empty overrides fall back to the schema", () => {
    const tool = enrichToolSnapshot(raw);
    expect(tool.name).toBe("Tasks API");
    expect(tool.display_name).toBe("Tasks API");
    expect(tool.description).toBe("Create and list tasks.");
    expect(tool.name_override).toBeNull();
    expect(tool.description_override).toBeNull();
  });

  test("set overrides win and stay readable", () => {
    const tool = enrichToolSnapshot({
      ...raw,
      name: "My Tasks",
      display_name: "My Tasks",
      description: "Team tracker.",
    });
    expect(tool.name).toBe("My Tasks");
    expect(tool.description).toBe("Team tracker.");
    expect(tool.name_override).toBe("My Tasks");
    expect(tool.description_override).toBe("Team tracker.");
  });

  test("an override equal to the schema's is still an override", () => {
    expect(
      enrichToolSnapshot({ ...raw, name: "Tasks API" }).name_override
    ).toBe("Tasks API");
  });

  test("MCP and built-in tools never fall back to a schema", () => {
    expect(enrichToolSnapshot({ ...raw, mcp_server_id: 7 }).name).toBe("");
    expect(
      enrichToolSnapshot({ ...raw, in_code_tool_id: "SearchTool" }).name
    ).toBe("");
  });
});
