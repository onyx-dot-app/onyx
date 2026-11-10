import React from "react";
import {
  copy,
  deferred,
  render,
  screen,
  setupUser,
} from "@tests/setup/test-utils";
import GroupSkillSettingRow, {
  type GroupSkillRow,
} from "@/views/admin/GroupsPage/GroupSkillSettingRow";
import { FetchError } from "@/lib/fetcher";
import type {
  GroupInstallationPolicy,
  GroupSkillSetting,
  GroupSkillTarget,
} from "@/lib/groupSkills/types";

jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));
Element.prototype.scrollIntoView = jest.fn();

const SKILL_ID = "22222222-2222-4222-8222-222222222222";
const skill: GroupSkillSetting = {
  skill_id: SKILL_ID,
  name: "Release notes",
  description: "Writes release notes",
  source: "COMPANY_MARKETPLACE",
  marketplace_id: "11111111-1111-4111-8111-111111111111",
  marketplace_name: "Company tools",
  permission: "VIEWER",
  company_installation_policy: "REQUIRED",
  group_installation_policy: "DEFAULT",
  effective_installation_policy: "DEFAULT",
  can_edit: true,
};

function msg(path: string, args: Record<string, string> = {}): string {
  return Object.entries(args).reduce(
    (text, [key, value]) => text.replace(`{${key}}`, value),
    copy(path)
  );
}
const policy = {
  REQUIRED: copy("skills.modals.share.installation.required"),
  DEFAULT: copy("skills.modals.share.installation.default"),
  AVAILABLE: copy("skills.modals.share.installation.available"),
  NOT_AVAILABLE: copy("skills.modals.share.installation.notAvailable"),
};
const inheritRequired = msg("admin.groups.skills.option.inherit", {
  policy: policy.REQUIRED,
});
const select = () =>
  screen.getByRole("combobox", {
    name: msg("admin.groups.skills.select.label", { name: "Release notes" }),
  });

type Save = (
  target: GroupSkillTarget,
  policy: GroupInstallationPolicy | null
) => Promise<void>;

function mount(setting: Partial<GroupSkillSetting> = {}, onSave?: Save) {
  const save = jest.fn<Promise<void>, Parameters<Save>>(
    onSave ?? (async () => undefined)
  );
  const row: GroupSkillRow = {
    kind: "skill",
    setting: { ...skill, ...setting },
  };
  render(<GroupSkillSettingRow row={row} onSave={save} />);
  return save;
}

async function pick(option: string) {
  const user = setupUser();
  await user.click(select());
  await user.click(
    screen.getByRole("option", {
      name: new RegExp(`^${option.replace(/[()]/g, "\\$&")}`),
    })
  );
}

describe("GroupSkillSettingRow", () => {
  it("explains the group and company settings and offers every value", async () => {
    mount();
    expect(select()).toHaveValue(policy.DEFAULT);
    expect(
      screen.getByText(
        msg("admin.groups.skills.status.overridden", {
          policy: policy.DEFAULT,
          company: policy.REQUIRED,
        })
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        msg("admin.groups.skills.skill.fromMarketplace", {
          marketplace: "Company tools",
        })
      )
    ).toBeInTheDocument();

    await setupUser().click(select());
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      expect.stringContaining(inheritRequired),
      expect.stringContaining(policy.AVAILABLE),
      expect.stringContaining(policy.DEFAULT),
      expect.stringContaining(policy.REQUIRED),
      expect.stringContaining(policy.NOT_AVAILABLE),
    ]);
  });

  it("shows an inherited row as following the company setting", () => {
    mount({ group_installation_policy: null });
    expect(select()).toHaveValue(inheritRequired);
    expect(
      screen.getByText(
        msg("admin.groups.skills.status.inherited", { policy: policy.REQUIRED })
      )
    ).toBeInTheDocument();
  });

  it.each([
    [policy.REQUIRED, "REQUIRED"],
    [policy.AVAILABLE, "AVAILABLE"],
    [policy.NOT_AVAILABLE, "NOT_AVAILABLE"],
    [inheritRequired, null],
  ])("saves %s as %s", async (label, value) => {
    const save = mount();
    await pick(label);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith({ kind: "skill", id: SKILL_ID }, value);
    expect(
      await screen.findByText(copy("admin.groups.skills.status.saved"))
    ).toBeInTheDocument();
  });

  it("can reverse a saved change before the parent refreshes", async () => {
    const save = mount({ group_installation_policy: null });
    await setupUser().click(select());
    await setupUser().click(screen.getByRole("option", { name: /^Available/ }));
    expect(select()).toHaveValue(policy.AVAILABLE);
    await setupUser().click(select());
    await setupUser().click(
      screen.getByRole("option", {
        name: new RegExp(`^${inheritRequired.replace(/[()]/g, "\\$&")}`),
      })
    );
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith(
      { kind: "skill", id: SKILL_ID },
      null
    );
  });

  it("adopts a newer server row after keeping a confirmed choice", async () => {
    const save = jest.fn(async () => undefined);
    const { rerender } = render(
      <GroupSkillSettingRow
        row={{ kind: "skill", setting: skill }}
        onSave={save}
      />
    );
    await pick(policy.AVAILABLE);
    expect(select()).toHaveValue(policy.AVAILABLE);
    expect(
      screen.getByText(
        msg("admin.groups.skills.status.overridden", {
          policy: policy.AVAILABLE,
          company: policy.REQUIRED,
        })
      )
    ).toBeInTheDocument();
    rerender(
      <GroupSkillSettingRow
        row={{
          kind: "skill",
          setting: {
            ...skill,
            group_installation_policy: "NOT_AVAILABLE",
          },
        }}
        onSave={save}
      />
    );
    expect(select()).toHaveValue(policy.NOT_AVAILABLE);
  });

  it("shows pending state and blocks a second save until the first settles", async () => {
    const pending = deferred<void>();
    const save = mount({}, () => pending.promise);
    await pick(policy.AVAILABLE);

    expect(
      screen.getByText(copy("admin.groups.skills.status.saving"))
    ).toBeInTheDocument();
    expect(select()).toHaveValue(policy.AVAILABLE);
    expect(select()).toBeEnabled();
    await pick(policy.NOT_AVAILABLE);
    expect(select()).toHaveValue(policy.AVAILABLE);
    expect(save).toHaveBeenCalledTimes(1);

    pending.resolve();
    expect(
      await screen.findByText(copy("admin.groups.skills.status.saved"))
    ).toBeInTheDocument();
    expect(select()).toBeEnabled();
    expect(select()).toHaveValue(policy.AVAILABLE);
  });

  it("keeps a failed choice with the server reason and retries it", async () => {
    let fail = true;
    const save = mount({}, async () => {
      if (fail) {
        throw new FetchError("failed", 400, {
          detail: "Outside the groups you manage",
        });
      }
    });
    await pick(policy.NOT_AVAILABLE);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      `${policy.NOT_AVAILABLE} is not saved. Outside the groups you manage`
    );
    expect(select()).toHaveValue(policy.NOT_AVAILABLE);

    fail = false;
    await setupUser().click(
      screen.getByRole("button", {
        name: msg("admin.groups.skills.retry.label", { name: "Release notes" }),
      })
    );
    expect(
      await screen.findByText(copy("admin.groups.skills.status.saved"))
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith(
      { kind: "skill", id: SKILL_ID },
      "NOT_AVAILABLE"
    );
  });

  it("keeps announcements mounted and returns retry focus to the setting", async () => {
    const pending = deferred<void>();
    let attempts = 0;
    mount({}, async () => {
      if (++attempts === 1) throw new Error("network");
      await pending.promise;
    });
    const status = screen.getByRole("status");
    const alert = screen.getByRole("alert");
    expect(status).toBeEmptyDOMElement();
    expect(alert).toBeEmptyDOMElement();
    await pick(policy.AVAILABLE);
    expect(alert).toHaveTextContent("is not saved");
    const retry = screen.getByRole("button", {
      name: msg("admin.groups.skills.retry.label", { name: "Release notes" }),
    });
    retry.focus();
    await setupUser().keyboard("{Enter}");
    expect(select()).toHaveFocus();
    expect(status).toHaveTextContent(copy("admin.groups.skills.status.saving"));
    expect(alert).toBeEmptyDOMElement();
    pending.resolve();
    await screen.findByText(copy("admin.groups.skills.status.saved"));
    expect(screen.getByRole("status")).toBe(status);
    expect(select()).toHaveFocus();
  });

  it("uses a plain reason when the server gives none", async () => {
    mount({}, async () => {
      throw new Error("network");
    });
    await pick(policy.AVAILABLE);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      `${policy.AVAILABLE} is not saved. ${copy("admin.groups.skills.status.failedReason")}`
    );
  });

  it("follows the server can_edit hint for read-only rows", async () => {
    const save = mount({ can_edit: false });
    expect(select()).toBeDisabled();
    expect(
      screen.getByText(copy("admin.groups.skills.status.readOnly"))
    ).toBeInTheDocument();
    await setupUser().click(select());
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
});
