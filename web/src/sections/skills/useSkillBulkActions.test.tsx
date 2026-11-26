import { useEffect } from "react";
import useSWR, { SWRConfig } from "swr";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type { CustomSkill, SkillsList } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSkillBulkActions } from "@/sections/skills/useSkillBulkActions";
import { toast } from "@opal/layouts";

const mockBulkUpdateSkills = jest.fn();
jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  bulkUpdateSkills: (...args: unknown[]) => mockBulkUpdateSkills(...args),
}));
jest.mock("@/lib/skills/cache", () => ({
  refreshSkillListsChecked: () => Promise.resolve(true),
}));
const mockSharingDraftStarted = jest.fn();
jest.mock("@/sections/modals/skills/BulkSkillSharingModal", () => ({
  __esModule: true,
  default: function SharingModal() {
    useEffect(() => mockSharingDraftStarted(), []);
    return null;
  },
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
      <button onClick={() => bulk.select(new Set([toggling.id, target.id]))}>
        select both
      </button>
      <button onClick={() => bulk.confirmDelete([target])}>
        delete target
      </button>
      <p data-testid="selection">{[...bulk.selectedIds].join(",")}</p>
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

test("a row delete keeps the selection of other plugins", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [target.id],
    failed: [],
  });
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);

  await user.click(screen.getByRole("button", { name: "select toggling" }));
  await user.click(screen.getByRole("button", { name: "delete target" }));
  await user.click(await screen.findByRole("button", { name: "Delete" }));

  await waitFor(() => expect(mockBulkUpdateSkills).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull()
  );
  expect(screen.getByTestId("selection")).toHaveTextContent(toggling.id);
});

test("a failed delete shows an error toast", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [],
    failed: [{ skill_id: target.id, detail: "In use" }],
  });
  const error = jest.spyOn(toast, "error");
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);

  await user.click(screen.getByRole("button", { name: "delete target" }));
  await user.click(await screen.findByRole("button", { name: "Delete" }));

  await waitFor(() =>
    expect(error).toHaveBeenCalledWith("1 plugin could not be updated")
  );
  error.mockRestore();
});

function CachedNames() {
  const { data } = useSWR<SkillsList>(SWR_KEYS.userSkills, null);
  return (
    <p data-testid="cached">
      {(data?.customs ?? []).map((skill) => skill.name).join(",")}
    </p>
  );
}

test("a delete drops the deleted plugin from the cached list", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [target.id],
    failed: [],
  });
  const list: SkillsList = { builtins: [], customs: [toggling, target] };
  const user = setupUser();
  render(
    <SWRConfig
      value={{
        provider: () => new Map([[SWR_KEYS.userSkills, { data: list }]]),
      }}
    >
      <Harness items={[toggling, target]} />
      <CachedNames />
    </SWRConfig>
  );
  expect(screen.getByTestId("cached")).toHaveTextContent("toggling,target");

  await user.click(screen.getByRole("button", { name: "delete target" }));
  await user.click(await screen.findByRole("button", { name: "Delete" }));

  await waitFor(() =>
    expect(screen.getByTestId("cached")).toHaveTextContent(/^toggling$/)
  );
});

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
