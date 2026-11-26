import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type { CustomSkill } from "@/lib/skills/types";
import { useSkillBulkActions } from "@/sections/skills/useSkillBulkActions";

const mockBulkUpdateSkills = jest.fn();
jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  bulkUpdateSkills: (...args: unknown[]) => mockBulkUpdateSkills(...args),
}));
jest.mock("@/lib/skills/cache", () => ({
  refreshSkillListsChecked: () => Promise.resolve(true),
}));
jest.mock("@/sections/modals/skills/BulkSkillSharingModal", () => ({
  __esModule: true,
  default: () => null,
}));

const toggling = customFixture({ id: "toggling", name: "toggling" });
const target = customFixture({ id: "target", name: "target" });

function Harness({ items }: { items: CustomSkill[] }) {
  const bulk = useSkillBulkActions({
    items,
    noun: "plugin",
    enablement: {
      isPending: (id) => id === toggling.id,
      enabledOf: (skill) => skill.enabled,
    },
  });
  return (
    <>
      <button onClick={() => bulk.select(new Set([toggling.id]))}>
        select toggling
      </button>
      <button onClick={() => bulk.confirmDelete([target])}>
        delete target
      </button>
      {bulk.modals}
    </>
  );
}

test("a pending toggle of a selected plugin does not block deleting another", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [target.id],
    failed: [],
  });
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);

  await user.click(screen.getByRole("button", { name: "select toggling" }));
  await user.click(screen.getByRole("button", { name: "delete target" }));
  await user.click(await screen.findByRole("button", { name: "Delete" }));

  await waitFor(() =>
    expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
      action: "delete",
      skill_ids: [target.id],
    })
  );
});
