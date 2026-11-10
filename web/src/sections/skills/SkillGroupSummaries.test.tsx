import { render, screen, setupUser } from "@tests/setup/test-utils";
import SkillGroupSummaries from "@/sections/skills/SkillGroupSummaries";

it("shows hidden groups and installation labels on keyboard focus", async () => {
  render(
    <SkillGroupSummaries
      summaries={[1, 2, 3].map((id) => ({
        group_id: id,
        group_name: `Group ${id}`,
        permission: "VIEWER",
        installation_policy: "REQUIRED",
        source: "marketplace",
      }))}
    />
  );
  const user = setupUser();
  await user.tab();
  expect(screen.getByText("+1 more group")).toHaveFocus();
  expect(await screen.findByRole("tooltip")).toHaveTextContent("Group 3");
  expect(screen.getByRole("tooltip")).toHaveTextContent("Required");
  expect(screen.getByRole("tooltip")).toHaveTextContent(/marketplace/i);
});
