import { render, screen, setupUser } from "@tests/setup/test-utils";
import { Tabs } from "@opal/components";

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
