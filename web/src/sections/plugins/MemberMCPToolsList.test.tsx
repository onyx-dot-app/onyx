import { render, screen, setupUser } from "@tests/setup/test-utils";
import MemberMCPToolsList from "@/sections/plugins/MemberMCPToolsList";
import { storedMcpTool } from "@/sections/plugins/__tests__/memberPluginFixtures";

const tools = [
  storedMcpTool,
  {
    ...storedMcpTool,
    id: 82,
    name: "list_teams",
    display_name: "List teams",
    description: "Browse workspace team membership.",
  },
];

test("shows tool descriptions inline without a disclosure", () => {
  render(<MemberMCPToolsList tools={tools} />);
  expect(screen.getByText(storedMcpTool.description)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Expand/ })
  ).not.toBeInTheDocument();
});

test("renders descriptions as plain text", () => {
  const description = "## Workflow\n<script>not executable</script>";
  render(<MemberMCPToolsList tools={[{ ...storedMcpTool, description }]} />);
  const text = screen.getByText(/## Workflow/);
  expect(text.textContent).toBe(description);
  expect(text.querySelector("script")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Copy code" })
  ).not.toBeInTheDocument();
});

test("search matches tool names and descriptions", async () => {
  render(<MemberMCPToolsList tools={tools} />);
  const user = setupUser();
  await user.type(
    screen.getByRole("textbox", { name: "Search tools" }),
    "MEMBERSHIP"
  );
  expect(screen.getByText("List teams")).toBeVisible();
  expect(screen.queryByText("Search issues")).not.toBeInTheDocument();
  expect(screen.getByText("Browse workspace team membership.")).toBeVisible();
  expect(screen.getByText("1 tool")).toBeVisible();
});

test("clearing an unmatched search restores the tool list", async () => {
  render(<MemberMCPToolsList tools={tools} />);
  const user = setupUser();
  const search = screen.getByRole("textbox", { name: "Search tools" });
  await user.type(search, "no match");
  expect(screen.getByText("No tools found")).toBeVisible();
  await user.clear(search);
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});
