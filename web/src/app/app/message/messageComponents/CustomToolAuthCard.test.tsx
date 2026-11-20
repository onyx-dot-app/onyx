import { render, screen, waitFor } from "@tests/setup/test-utils";
import CustomToolAuthCard from "@/app/app/message/messageComponents/CustomToolAuthCard";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import type { ToolSnapshot } from "@/lib/tools/types";

const mockTools: { current: ToolSnapshot[] } = { current: [] };

jest.mock("@/lib/tools/hooks", () => ({
  useAvailableTools: () => ({ tools: mockTools.current }),
}));

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
  integration_id: 4,
};

test("links the sign-in to the integration that the tool list gives", () => {
  mockTools.current = [tool];
  render(<CustomToolAuthCard toolName="Example" toolId={1} />);
  expect(screen.getByRole("link", { name: /connect/i })).toHaveAttribute(
    "href",
    "/app/customize/integrations/4?tab=configuration"
  );
});

test("shows nothing for a tool with no integration", () => {
  mockTools.current = [{ ...tool, integration_id: null }];
  const { container } = render(
    <CustomToolAuthCard toolName="Example" toolId={1} />
  );
  expect(container).toBeEmptyDOMElement();
});

function Statuses() {
  useMemberIntegrations();
  return null;
}

test("reads the integration statuses again", async () => {
  mockTools.current = [tool];
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify([])));
  const reads = () =>
    fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/integrations"
    ).length;
  const { rerender } = render(<Statuses />);
  await waitFor(() => expect(reads()).toBe(1));
  rerender(
    <>
      <Statuses />
      <CustomToolAuthCard toolName="Example" toolId={1} />
    </>
  );
  await waitFor(() => expect(reads()).toBe(2));
  fetchMock.mockRestore();
});
