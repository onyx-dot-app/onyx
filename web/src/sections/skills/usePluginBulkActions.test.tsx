import { useEffect } from "react";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type { CustomSkill } from "@/lib/skills/types";
import { usePluginBulkActions } from "@/sections/skills/usePluginBulkActions";

const mockSharingDraftStarted = jest.fn();
let mockSharingOpen = false;
jest.mock("@/sections/modals/skills/BulkSkillSharingModal", () => ({
  __esModule: true,
  default: function SharingModal({ open }: { open: boolean }) {
    useEffect(() => mockSharingDraftStarted(), []);
    mockSharingOpen = open;
    return null;
  },
}));

const toggling = customFixture({ id: "toggling", name: "toggling" });
const target = customFixture({
  id: "target",
  name: "target",
  user_permission: "OWNER",
});

function Harness({ items }: { items: CustomSkill[] }) {
  const bulk = usePluginBulkActions({
    items,
    noun: "plugin",
    enablement: {
      isPending: (id) => id === toggling.id,
      enabledOf: (skill) => skill.enabled,
    },
  });
  return (
    <>
      <button onClick={() => bulk.select(new Set([toggling.id, target.id]))}>
        select both
      </button>
      <button onClick={() => bulk.select(new Set([target.id]))}>
        select target
      </button>
      <button onClick={() => bulk.confirmDelete([target])}>
        delete target
      </button>
      <button onClick={() => bulk.confirmDelete([toggling, target])}>
        delete both
      </button>
      {bulk.toolbarActions}
      {bulk.modals}
    </>
  );
}

test("a selected plugin that leaves the list starts a new sharing draft", async () => {
  const user = setupUser();
  const { rerender } = render(<Harness items={[toggling, target]} />);
  await user.click(screen.getByRole("button", { name: "select both" }));
  mockSharingDraftStarted.mockClear();

  rerender(<Harness items={[toggling]} />);
  expect(mockSharingDraftStarted).toHaveBeenCalledTimes(1);

  rerender(<Harness items={[toggling, target]} />);
  expect(mockSharingDraftStarted).toHaveBeenCalledTimes(2);
});

test("Share closes when a sync removes every selected plugin", async () => {
  const user = setupUser();
  const { rerender } = render(<Harness items={[toggling, target]} />);
  await user.click(screen.getByRole("button", { name: "select target" }));
  await user.click(screen.getByRole("button", { name: /share/i }));
  expect(mockSharingOpen).toBe(true);

  rerender(<Harness items={[toggling]} />);

  expect(mockSharingOpen).toBe(false);
});

test("a single delete confirm names the plugin", async () => {
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);
  await user.click(screen.getByRole("button", { name: "delete target" }));

  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("Delete target?");
  expect(dialog).toHaveTextContent(
    "This deletes the plugin for everyone who has access. This cannot be undone."
  );
  expect(dialog).not.toHaveTextContent(/selected/);
  expect(within(dialog).getByRole("list")).toHaveTextContent("target");
});

test("a delete confirm for many plugins counts them", async () => {
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);
  await user.click(screen.getByRole("button", { name: "delete both" }));

  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("Delete 2 plugins?");
  expect(within(dialog).getByRole("list")).toHaveTextContent("toggling");
});
