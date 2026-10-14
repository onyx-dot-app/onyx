import { render, screen, setupUser } from "@tests/setup/test-utils";
import MCPActionCard from "@/sections/actions/MCPActionCard";
import { ActionStatus } from "@/lib/tools/types";

function renderCard(status = ActionStatus.PENDING) {
  const open = jest.fn();
  render(
    <MCPActionCard
      title="Example MCP"
      description="Tools for the workspace"
      status={status}
      onOpen={open}
    />
  );
  return { open };
}

test("clicking the card opens the same settings once", async () => {
  const { open } = renderCard();
  const user = setupUser();
  await user.click(
    screen.getByRole("article", { name: "Example MCP MCP server card" })
  );
  expect(open).toHaveBeenCalledTimes(1);
});

test("has no nested icon actions or rename control", () => {
  renderCard();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

test.each(["{Enter}", " "])(
  "opens card settings with the keyboard using %s",
  async (key) => {
    const { open } = renderCard();
    const user = setupUser();
    await user.tab();
    await user.keyboard(key);
    expect(open).toHaveBeenCalledTimes(1);
  }
);

test("the status footer remains part of the card click target", async () => {
  const { open } = renderCard();
  await setupUser().click(screen.getByText("Setup incomplete"));
  expect(open).toHaveBeenCalledTimes(1);
});

test("pending cards show setup status below the card content", () => {
  renderCard();
  expect(screen.getByText("Setup incomplete")).toBeVisible();
  expect(screen.queryByText("(Not Authenticated)")).not.toBeInTheDocument();
});

test.each([
  [ActionStatus.CONNECTED, "Ready · 3 tools"],
  [ActionStatus.PENDING, "Setup incomplete"],
  [ActionStatus.FETCHING, "Loading tools"],
  [ActionStatus.DISCONNECTED, "Disconnected"],
])("shows one server configuration status for %s", (status, label) => {
  render(
    <MCPActionCard
      title="Example MCP"
      description="Workspace tools"
      status={status}
      toolCount={3}
    />
  );
  expect(screen.getByText(label)).toBeVisible();
  expect(screen.queryByText("(Disconnected)")).not.toBeInTheDocument();
  expect(screen.queryByText("(Not Authenticated)")).not.toBeInTheDocument();
});
