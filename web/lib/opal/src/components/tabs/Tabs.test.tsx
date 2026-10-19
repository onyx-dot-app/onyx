import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { Button, Tabs } from "@opal/components";

function ConditionalTabs({ showPermissions }: { showPermissions: boolean }) {
  return (
    <Tabs defaultValue="tools">
      <Tabs.List>
        <Tabs.Trigger value="tools">Tools</Tabs.Trigger>
        {showPermissions && (
          <Tabs.Trigger value="permissions">Permissions</Tabs.Trigger>
        )}
      </Tabs.List>
      <Tabs.Content value="tools">Available tools</Tabs.Content>
      {showPermissions && (
        <Tabs.Content value="permissions">Tool permissions</Tabs.Content>
      )}
    </Tabs>
  );
}

it("allocates grid columns only for visible tabs as conditional tabs change", async () => {
  const user = setupUser();
  const { rerender } = render(<ConditionalTabs showPermissions={false} />);
  expect(screen.getByRole("tablist")).toHaveStyle({
    gridTemplateColumns: "repeat(1, 1fr)",
  });
  expect(screen.getAllByRole("tab")).toHaveLength(1);
  rerender(<ConditionalTabs showPermissions />);
  expect(screen.getByRole("tablist")).toHaveStyle({
    gridTemplateColumns: "repeat(2, 1fr)",
  });
  await user.click(screen.getByRole("tab", { name: "Permissions" }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Tool permissions");
});

// ── Keyboard ─────────────────────────────────────────────────────────────────

function FilterTabs({ dir }: { dir?: "ltr" | "rtl" }) {
  return (
    <>
      <Button prominence="secondary">Before</Button>
      <Tabs defaultValue="all" dir={dir}>
        <Tabs.List>
          <Tabs.Trigger value="all">All</Tabs.Trigger>
          <Tabs.Trigger value="mcp">MCP</Tabs.Trigger>
          <Tabs.Trigger value="apps" disabled tooltip="Upgrade">
            Apps
          </Tabs.Trigger>
          <Tabs.Trigger value="openapi">OpenAPI</Tabs.Trigger>
        </Tabs.List>
      </Tabs>
      <Button prominence="secondary">After</Button>
    </>
  );
}

describe("keyboard", () => {
  it("Tab enters on the selected tab, then leaves the tab list", async () => {
    const user = setupUser();
    render(<FilterTabs />);
    await user.click(screen.getByRole("button", { name: "Before" }));
    await user.tab();
    expect(screen.getByRole("tab", { name: "All" })).toHaveFocus();
    expect(screen.getByRole("tablist")).toHaveAttribute("data-focus-ring");
    await user.tab();
    expect(screen.getByRole("button", { name: "After" })).toHaveFocus();
    expect(screen.getByRole("tablist")).not.toHaveAttribute("data-focus-ring");
    await user.tab({ shift: true });
    expect(screen.getByRole("tab", { name: "All" })).toHaveFocus();
  });

  it("moves with Left and Right, skipping a disabled tab, and selects with Enter", async () => {
    const user = setupUser();
    render(<FilterTabs />);
    await user.click(screen.getByRole("button", { name: "Before" }));
    await user.tab();
    await user.keyboard("{ArrowRight}");
    const mcp = screen.getByRole("tab", { name: "MCP" });
    expect(mcp).toHaveFocus();
    expect(mcp).toHaveAttribute("aria-selected", "false");
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "OpenAPI" })).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(mcp).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(mcp).toHaveAttribute("aria-selected", "true");
    // Tab leaves the tab list, and Shift+Tab comes back to the selected tab.
    await user.tab();
    await user.tab({ shift: true });
    expect(mcp).toHaveFocus();
  });

  it("focuses a clicked tab, and shows the ring only from the arrows until Escape", async () => {
    const user = setupUser();
    render(<FilterTabs />);
    const list = screen.getByRole("tablist");
    // Safari and Firefox on macOS do not focus a button on click.
    const mcp = screen.getByRole("tab", { name: "MCP" });
    fireEvent.mouseDown(mcp);
    expect(mcp).toHaveFocus();
    expect(mcp).toHaveAttribute("aria-selected", "true");
    expect(list).not.toHaveAttribute("data-focus-ring");
    // The ring waits for focus to land on the next tab.
    fireEvent.keyDown(mcp, { key: "ArrowRight" });
    expect(list).not.toHaveAttribute("data-focus-ring");
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "OpenAPI" })).toHaveFocus()
    );
    expect(list).toHaveAttribute("data-focus-ring");
    await user.keyboard("{Escape}");
    expect(list).not.toHaveAttribute("data-focus-ring");
    expect(screen.getByRole("tab", { name: "OpenAPI" })).not.toHaveFocus();
    fireEvent.mouseDown(mcp);
    expect(list).not.toHaveAttribute("data-focus-ring");
  });

  it("Escape on a control beside the tabs keeps its focus", async () => {
    const user = setupUser();
    render(
      <Tabs defaultValue="a" variant="pill">
        <Tabs.List
          rightChildren={<Button prominence="tertiary">Expand</Button>}
        >
          <Tabs.Trigger value="a">A</Tabs.Trigger>
          <Tabs.Trigger value="b">B</Tabs.Trigger>
        </Tabs.List>
      </Tabs>
    );
    const expand = screen.getByRole("button", { name: "Expand" });
    await user.click(expand);
    await user.keyboard("{Escape}");
    expect(expand).toHaveFocus();
  });

  it("does not focus a tab on a right click or Ctrl-click", () => {
    render(<FilterTabs />);
    const mcp = screen.getByRole("tab", { name: "MCP" });
    fireEvent.mouseDown(mcp, { button: 2 });
    expect(mcp).not.toHaveFocus();
    fireEvent.mouseDown(mcp, { button: 0, ctrlKey: true });
    expect(mcp).not.toHaveFocus();
  });

  it("follows the arrow's direction in a right-to-left layout", async () => {
    const user = setupUser();
    render(<FilterTabs dir="rtl" />);
    await user.click(screen.getByRole("button", { name: "Before" }));
    await user.tab();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "MCP" })).toHaveFocus();
  });
});
