import React from "react";
import { useSWRConfig } from "swr";
import {
  copy,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import GroupSkillsTab from "@/views/admin/GroupsPage/GroupSkillsTab";
import type {
  GroupMarketplaceSetting,
  GroupSkillSetting,
  UserGroupSkills,
} from "@/lib/groupSkills/types";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));
Element.prototype.scrollIntoView = jest.fn();

const GROUP_ID = 7;
const MARKETPLACE_ID = "11111111-1111-4111-8111-111111111111";
const SKILL_ID = "22222222-2222-4222-8222-222222222222";
const SKILLS_URL = SWR_KEYS.userGroupSkills(GROUP_ID);

const marketplace: GroupMarketplaceSetting = {
  marketplace_id: MARKETPLACE_ID,
  name: "Company tools",
  following_skill_count: 3,
  permission: "VIEWER",
  company_installation_policy: "AVAILABLE",
  group_installation_policy: null,
  effective_installation_policy: "AVAILABLE",
  can_edit: true,
};
const skill: GroupSkillSetting = {
  skill_id: SKILL_ID,
  name: "Release notes",
  description: "Writes release notes",
  source: "UPLOADED",
  marketplace_id: null,
  marketplace_name: null,
  permission: "VIEWER",
  company_installation_policy: "REQUIRED",
  group_installation_policy: "DEFAULT",
  effective_installation_policy: "DEFAULT",
  can_edit: true,
};

const policy = {
  REQUIRED: copy("skills.modals.share.installation.required"),
  AVAILABLE: copy("skills.modals.share.installation.available"),
  NOT_AVAILABLE: copy("skills.modals.share.installation.notAvailable"),
};
const selectFor = (name: string) =>
  screen.getByRole("combobox", {
    name: copy("admin.groups.skills.select.label").replace("{name}", name),
  });
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

let current: UserGroupSkills;
let fetchSpy: jest.SpiedFunction<typeof fetch>;
let putHandler: () => Promise<Response>;

beforeEach(() => {
  current = { marketplaces: [marketplace], skills: [skill] };
  putHandler = async () => json(current);
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) => {
      if (input === SKILLS_URL) return json(current);
      if (init?.method === "PUT") return putHandler();
      throw new Error(`Unexpected request: ${String(input)}`);
    });
});
afterEach(() => jest.restoreAllMocks());

const puts = () =>
  fetchSpy.mock.calls.filter(([, init]) => init?.method === "PUT");
const gets = () =>
  fetchSpy.mock.calls.filter(([input]) => input === SKILLS_URL).length;

async function pick(name: string, option: string) {
  const user = setupUser();
  await user.click(selectFor(name));
  await user.click(
    screen.getByRole("option", { name: new RegExp(`^${option}`) })
  );
}

describe("GroupSkillsTab", () => {
  it("groups marketplace rows apart from directly shared Skills", async () => {
    render(<GroupSkillsTab groupId={GROUP_ID} />);
    const marketplaces = await screen.findByRole("region", {
      name: copy("admin.groups.skills.marketplaces.title"),
    });
    const direct = screen.getByRole("region", {
      name: copy("admin.groups.skills.direct.title"),
    });
    expect(
      within(marketplaces).getByRole("group", { name: "Company tools" })
    ).toBeInTheDocument();
    expect(
      within(marketplaces).getByText(/3 Skills follow/)
    ).toBeInTheDocument();
    expect(
      within(direct).getByRole("group", { name: "Release notes" })
    ).toBeInTheDocument();
    expect(screen.getByText(copy("admin.groups.skills.intro"))).toBeVisible();
  });

  it.each([
    [
      "Release notes",
      policy.NOT_AVAILABLE,
      "NOT_AVAILABLE",
      `skills/${SKILL_ID}`,
    ],
    [
      "Company tools",
      policy.REQUIRED,
      "REQUIRED",
      `marketplaces/${MARKETPLACE_ID}`,
    ],
  ])("saves %s as %s on its own route", async (name, label, value, path) => {
    render(<GroupSkillsTab groupId={GROUP_ID} />);
    await screen.findByRole("group", { name });
    await pick(name, label);
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]?.[0]).toBe(
      `/api/manage/admin/user-group/${GROUP_ID}/${path}/installation-policy`
    );
    expect(JSON.parse(String(puts()[0]?.[1]?.body))).toEqual({
      installation_policy: value,
    });
  });

  it("shows the list the server returns after a save", async () => {
    putHandler = async () => {
      current = {
        ...current,
        skills: [
          {
            ...skill,
            group_installation_policy: null,
            effective_installation_policy: "REQUIRED",
          },
        ],
      };
      return json(current);
    };
    render(<GroupSkillsTab groupId={GROUP_ID} />);
    await screen.findByRole("group", { name: "Release notes" });
    await pick("Release notes", "Company setting");
    const row = screen.getByRole("group", { name: "Release notes" });
    expect(
      await within(row).findByText(
        copy("admin.groups.skills.status.inherited").replace(
          "{policy}",
          policy.REQUIRED
        )
      )
    ).toBeInTheDocument();
    expect(JSON.parse(String(puts()[0]?.[1]?.body))).toEqual({
      installation_policy: null,
    });
  });

  it("refetches once overlapping saves settle", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const queue = [first, second];
    putHandler = () => queue.shift()?.promise ?? Promise.resolve(json(current));
    render(<GroupSkillsTab groupId={GROUP_ID} />);
    await screen.findByRole("group", { name: "Release notes" });
    await pick("Release notes", policy.AVAILABLE);
    await pick("Company tools", policy.REQUIRED);
    expect(puts()).toHaveLength(2);
    const before = gets();

    second.resolve(json(current));
    first.resolve(json(current));
    await waitFor(() => expect(gets()).toBe(before + 1));
  });

  it.each([403, 404])(
    "explains a %s from the server as no access",
    async (status) => {
      fetchSpy.mockImplementation(async () =>
        json({ detail: "Not allowed" }, status)
      );
      render(<GroupSkillsTab groupId={GROUP_ID} />);
      expect(
        await screen.findByText(copy("admin.groups.skills.noAccess.title"))
      ).toBeInTheDocument();
    }
  );

  it("offers a retry when loading fails", async () => {
    let fail = true;
    fetchSpy.mockImplementation(async () =>
      fail ? json({ detail: "Down" }, 500) : json(current)
    );
    render(<GroupSkillsTab groupId={GROUP_ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      copy("admin.groups.skills.loadFailed")
    );
    fail = false;
    await setupUser().click(
      screen.getByRole("button", {
        name: copy("admin.groups.skills.retry.button"),
      })
    );
    expect(
      await screen.findByRole("group", { name: "Release notes" })
    ).toBeInTheDocument();
  });

  it.each([500, 401, 403, 404])(
    "handles a %s refetch with a failed row draft",
    async (status) => {
      function Refresh() {
        const { mutate } = useSWRConfig();
        return (
          <button
            onClick={() => void mutate(SKILLS_URL).catch(() => undefined)}
          >
            Refetch
          </button>
        );
      }
      putHandler = async () => json({ detail: "Save failed" }, 500);
      render(
        <>
          <Refresh />
          <GroupSkillsTab groupId={GROUP_ID} />
        </>
      );
      await screen.findByRole("group", { name: "Release notes" });
      await pick("Release notes", policy.AVAILABLE);
      await screen.findByRole("button", {
        name: "Retry the setting for Release notes",
      });
      fetchSpy.mockImplementation(async () =>
        json({ detail: "Refetch failed" }, status)
      );
      await setupUser().click(screen.getByRole("button", { name: "Refetch" }));
      await screen.findByText(
        copy(
          status === 500
            ? "admin.groups.skills.loadFailed"
            : "admin.groups.skills.noAccess.title"
        )
      );
      if (status === 500)
        expect(selectFor("Release notes")).toHaveValue(policy.AVAILABLE);
      else
        expect(
          screen.queryByRole("group", { name: "Release notes" })
        ).not.toBeInTheDocument();
      fetchSpy.mockImplementation(async () => json(current));
      await setupUser().click(screen.getByRole("button", { name: "Refetch" }));
      await screen.findByRole("group", { name: "Release notes" });
      expect(selectFor("Release notes")).toHaveValue(
        status === 500 ? policy.AVAILABLE : "Installed by default"
      );
    }
  );

  it("shows an empty state when nothing is shared", async () => {
    current = { marketplaces: [], skills: [] };
    render(<GroupSkillsTab groupId={GROUP_ID} />);
    expect(
      await screen.findByText(copy("admin.groups.skills.empty.title"))
    ).toBeInTheDocument();
  });
});
