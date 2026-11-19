import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import AdminSkillsTable from "@/sections/skills/AdminSkillsTable";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type { CustomSkill } from "@/lib/skills/types";

const published = customFixture({
  id: "published",
  name: "weekly-report",
  user_permission: "OWNER",
  owner: { id: "me", email: "me@example.com" },
  public_permission: "VIEWER",
  installation_policy: "REQUIRED",
  current_version_number: 3,
  published_version_number: 2,
  group_summaries: [
    {
      group_id: 1,
      group_name: "Sales",
      permission: null,
      installation_policy: "AVAILABLE",
    },
  ],
});
const viewed = customFixture({
  id: "viewed",
  name: "sql-helper",
  user_permission: "VIEWER",
  owner: { id: "other", email: "other@example.com" },
  public_permission: null,
  is_personal: true,
  current_version_number: 1,
  published_version_number: null,
});

function renderTable(skills: CustomSkill[]) {
  const onShare = jest.fn();
  const onDelete = jest.fn();
  const onOpen = jest.fn();
  render(
    <AdminSkillsTable
      skills={skills}
      selectedIds={new Set()}
      onSelectionChange={jest.fn()}
      busy={false}
      isPending={() => false}
      enabledOf={(skill) => skill.enabled}
      onEnabledChange={jest.fn()}
      onOpen={onOpen}
      onShare={onShare}
      onDelete={onDelete}
    />
  );
  return { onShare, onDelete, onOpen };
}

test("shows the source, version, audience and groups of each skill", () => {
  renderTable([published, viewed]);
  const row = screen.getByRole("row", { name: "Open weekly-report" });
  expect(within(row).getByText("Organization library")).toBeVisible();
  expect(within(row).getByText("v3 · v2 live")).toBeVisible();
  expect(within(row).getAllByText("Required", { exact: true })).toHaveLength(2);
  expect(within(row).getByText("Groups: Sales: Available")).toBeVisible();

  const other = screen.getByRole("row", { name: "Open sql-helper" });
  expect(within(other).getByText("other@example.com")).toBeVisible();
  expect(within(other).getByText("Only the owner")).toBeVisible();
});

test("Share and Delete call back for an editor, and a viewer gets no Share", async () => {
  const user = setupUser();
  const { onShare, onDelete, onOpen } = renderTable([published, viewed]);

  await user.click(
    screen.getByRole("button", { name: "More for weekly-report" })
  );
  await user.click(screen.getByRole("menuitem", { name: "Share" }));
  expect(onShare).toHaveBeenCalledWith(published);

  await user.click(
    screen.getByRole("button", { name: "More for weekly-report" })
  );
  await user.click(screen.getByRole("menuitem", { name: "Delete" }));
  expect(onDelete).toHaveBeenCalledWith(published);
  expect(onOpen).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "More for sql-helper" }));
  expect(
    screen.queryByRole("menuitem", { name: "Share" })
  ).not.toBeInTheDocument();
});
