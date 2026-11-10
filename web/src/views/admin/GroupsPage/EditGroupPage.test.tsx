import React, { useState } from "react";
import { Button, Text } from "@opal/components";
import {
  copy,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import EditGroupPage from "@/views/admin/GroupsPage/EditGroupPage";
import type { UserGroupSkills } from "@/lib/groupSkills/types";
import { userGroupUrl } from "@/hooks/useGroups";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission, type UserGroup } from "@/lib/types";

jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));
Element.prototype.scrollIntoView = jest.fn();

let mockPermissions: string[];
let mockCraftAvailable: boolean;
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { id: "me" },
    permissions: [],
    adminCapabilities: mockPermissions,
  }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    tier: "enterprise",
    appName: "Onyx",
    onyx_craft_available: mockCraftAvailable,
  }),
}));
const mockGo = jest.fn();
jest.mock("@opal/navigation", () => ({
  ...jest.requireActual("@opal/navigation"),
  useNavigation: () => ({ go: mockGo }),
}));
jest.mock("@/views/admin/GroupsPage/useGroupMemberCandidates", () => ({
  __esModule: true,
  default: () => ({ rows: [], isLoading: false, error: undefined }),
}));
jest.mock("@/views/admin/GroupsPage/SharedGroupResources", () => ({
  __esModule: true,
  default: () => null,
}));
// Stands in for a section that keeps its own draft, like the spending cards.
jest.mock("@/views/admin/GroupsPage/GroupSpendingLimitsSection", () => ({
  __esModule: true,
  default: function SpendingDraft() {
    const [count, setCount] = useState(0);
    return (
      <>
        <Text>{`Spending draft ${count}`}</Text>
        <Button onClick={() => setCount(count + 1)}>Change spending</Button>
      </>
    );
  },
}));

const GROUP_ID = 7;
const SKILL_ID = "22222222-2222-4222-8222-222222222222";
const SKILLS_URL = SWR_KEYS.userGroupSkills(GROUP_ID);
const POLICY_URL = `/api/manage/admin/user-group/${GROUP_ID}/skills/${SKILL_ID}/installation-policy`;

let group: UserGroup;
const skills: UserGroupSkills = {
  marketplaces: [],
  skills: [
    {
      skill_id: SKILL_ID,
      name: "Release notes",
      description: "Writes release notes",
      source: "UPLOADED",
      marketplace_id: null,
      marketplace_name: null,
      permission: "VIEWER",
      company_installation_policy: "AVAILABLE",
      group_installation_policy: null,
      effective_installation_policy: "AVAILABLE",
      can_edit: true,
    },
  ],
};
let fetchSpy: jest.SpiedFunction<typeof fetch>;
const json = (body: unknown) => new Response(JSON.stringify(body));

beforeEach(() => {
  mockPermissions = [Permission.MANAGE_SKILLS];
  mockCraftAvailable = true;
  group = {
    id: GROUP_ID,
    name: "Engineering",
    users: [],
    member_count: 0,
    active_member_count: 0,
    manager_ids: [],
    cc_pairs: [],
    document_sets: [],
    personas: [],
    is_up_to_date: true,
    is_up_for_deletion: false,
    is_default: false,
    incognito_enabled: false,
    permissions: { manage: true, manage_members: true },
  };
  fetchSpy = jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (input === userGroupUrl(GROUP_ID)) return json(group);
    if (input === SKILLS_URL || input === POLICY_URL) return json(skills);
    return json({});
  });
});
afterEach(() => jest.restoreAllMocks());

const requested = (url: string) =>
  fetchSpy.mock.calls.some(([input]) => input === url);
const skillsTabName = { name: copy("admin.groups.edit.tabs.skills") };
const skillsTab = () => screen.queryByRole("tab", skillsTabName);
const openSkillsTab = () => screen.getByRole("tab", skillsTabName);

describe("EditGroupPage Skills tab", () => {
  it("keeps group drafts across tabs and saves Skill settings apart from Save", async () => {
    const user = setupUser();
    render(<EditGroupPage groupId={GROUP_ID} />);
    const search = await screen.findByPlaceholderText(
      copy("admin.groups.members.searchMembers.placeholder")
    );
    expect(requested(SKILLS_URL)).toBe(false);

    await user.type(search, "ada");
    await user.click(screen.getByRole("button", { name: "Change spending" }));
    await user.click(openSkillsTab());

    const select = await screen.findByRole("combobox", {
      name: "Install setting for Release notes",
    });
    await user.click(select);
    await user.click(screen.getByRole("option", { name: /^Required/ }));
    await waitFor(() =>
      expect(
        fetchSpy.mock.calls.filter(([input]) => input === POLICY_URL)
      ).toHaveLength(1)
    );

    await user.click(
      screen.getByRole("tab", { name: copy("admin.groups.edit.tabs.group") })
    );
    expect(
      screen.getByPlaceholderText(
        copy("admin.groups.members.searchMembers.placeholder")
      )
    ).toHaveValue("ada");
    expect(screen.getByText("Spending draft 1")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: copy("admin.groups.edit.submit.label"),
      })
    );
    await waitFor(() => expect(mockGo).toHaveBeenCalledWith("/admin/groups"));
    expect(
      fetchSpy.mock.calls.filter(([input]) => input === POLICY_URL)
    ).toHaveLength(1);
  });

  it("lets a member manager edit rows the server marks editable", async () => {
    // Skill rows follow can_edit, not the group's sharing rights.
    group = { ...group, permissions: { manage_members: true } };
    render(<EditGroupPage groupId={GROUP_ID} />);
    await screen.findByPlaceholderText(
      copy("admin.groups.members.searchMembers.placeholder")
    );
    await setupUser().click(openSkillsTab());
    expect(
      await screen.findByRole("combobox", {
        name: "Install setting for Release notes",
      })
    ).toBeEnabled();
  });

  it.each([
    ["without Manage Skills", [], true],
    ["when Craft is off", [Permission.MANAGE_SKILLS], false],
  ])("hides the tab %s", async (_label, permissions, craft) => {
    mockPermissions = permissions;
    mockCraftAvailable = craft;
    render(<EditGroupPage groupId={GROUP_ID} />);
    await screen.findByPlaceholderText(
      copy("admin.groups.form.name.placeholder")
    );
    expect(skillsTab()).not.toBeInTheDocument();
    expect(requested(SKILLS_URL)).toBe(false);
  });

  it("keeps the group read boundary for callers who cannot manage members", async () => {
    group = { ...group, permissions: {} };
    render(<EditGroupPage groupId={GROUP_ID} />);
    const notFound = await screen.findByText(
      copy("admin.groups.edit.notFound.title")
    );
    expect(within(document.body).queryByRole("tablist")).toBeNull();
    expect(notFound).toBeInTheDocument();
    expect(requested(SKILLS_URL)).toBe(false);
  });
});
