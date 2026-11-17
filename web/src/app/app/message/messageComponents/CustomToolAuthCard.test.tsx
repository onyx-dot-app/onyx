import { render, screen } from "@tests/setup/test-utils";
import CustomToolAuthCard from "@/app/app/message/messageComponents/CustomToolAuthCard";
import type { ToolSnapshot } from "@/lib/tools/types";

const tool: ToolSnapshot = {
  id: 1,
  name: "example",
  display_name: "Example",
  description: "Example tool",
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  plugin_ids: ["plugin-1"],
};

test("links the sign-in to the integrations of the tool's plugin", () => {
  render(<CustomToolAuthCard toolName="Example" toolId={1} tools={[tool]} />);
  expect(screen.getByRole("link", { name: /connect/i })).toHaveAttribute(
    "href",
    "/app/plugins/plugin-1?tab=integrations"
  );
});

test("shows nothing for a tool with no plugin", () => {
  const { container } = render(
    <CustomToolAuthCard
      toolName="Example"
      toolId={1}
      tools={[{ ...tool, plugin_ids: [] }]}
    />
  );
  expect(container).toBeEmptyDOMElement();
});
