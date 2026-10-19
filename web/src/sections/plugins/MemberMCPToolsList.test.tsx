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

test("descriptions stay collapsed until their tool is expanded", async () => {
  render(<MemberMCPToolsList tools={tools} />);
  const user = setupUser();
  expect(screen.queryByText(storedMcpTool.description)).not.toBeInTheDocument();
  const expand = screen.getByRole("button", { name: "Expand Search issues" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  await user.click(expand);
  expect(screen.getByText(storedMcpTool.description)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Fold Search issues" })
  ).toHaveAttribute("aria-expanded", "true");
});

test("expanded descriptions use compact code while preserving the original text", async () => {
  const description =
    "## Workflow\n\n1. Read the issue.\n2. Use `issue_id`.\n\n<script>not executable</script>";
  render(<MemberMCPToolsList tools={[{ ...storedMcpTool, description }]} />);
  await setupUser().click(
    screen.getByRole("button", { name: "Expand Search issues" })
  );
  const code = screen.getByText(/## Workflow/);
  expect(code.tagName).toBe("CODE");
  expect(code.textContent).toBe(description);
  expect(code.querySelector("script")).toBeNull();
  expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
});

test("search matches names and hidden descriptions without expanding them", async () => {
  render(<MemberMCPToolsList tools={tools} />);
  const user = setupUser();
  await user.type(
    screen.getByRole("textbox", { name: "Search tools" }),
    "MEMBERSHIP"
  );
  expect(screen.getByText("List teams")).toBeVisible();
  expect(screen.queryByText("Search issues")).not.toBeInTheDocument();
  expect(
    screen.queryByText("Browse workspace team membership.")
  ).not.toBeInTheDocument();
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
