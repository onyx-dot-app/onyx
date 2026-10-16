/** @jest-environment jsdom */

import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import ActionPolicyEditorModal, {
  type PolicyEditorItem,
} from "@/app/craft/v1/apps/admin/ActionPolicyEditorModal";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/admin/craft/apps",
}));

const ITEMS: PolicyEditorItem[] = [
  {
    id: "read",
    name: "Read",
    description: "Read tickets",
    defaultPolicy: "ALWAYS",
  },
  {
    id: "write",
    name: "Write",
    description: "Write tickets",
    defaultPolicy: "ASK",
  },
];

async function renderEditor(
  initialPolicies: Record<string, ActionPolicy> = {},
  items: PolicyEditorItem[] = ITEMS
) {
  const onSave = jest.fn().mockResolvedValue(undefined);
  render(
    <ActionPolicyEditorModal
      onClose={jest.fn()}
      title="App settings"
      displayUrl="https://example.com"
      fields={[]}
      initialFieldValues={{}}
      policyItems={items}
      initialPolicies={initialPolicies}
      emptyPoliciesMessage="No actions"
      saveLabel="Save"
      onSave={onSave}
      allowPristineSave
    />
  );
  await setupUser().click(screen.getByRole("tab", { name: "Permissions" }));
  return { onSave };
}

function expectValidSelection(label: string) {
  expect(screen.getByRole("combobox")).toHaveValue(label);
  expect(
    screen.queryByText("Please select a valid option from the list")
  ).not.toBeInTheDocument();
}

const DEFAULT_POLICIES: Record<string, ActionPolicy>[] = [
  {},
  { read: "ALWAYS" },
  { read: "ALWAYS", write: "ASK" },
];

describe("ActionPolicyEditorModal permissions", () => {
  it.each(DEFAULT_POLICIES)(
    "shows registry defaults without validation errors or changing stored policies: %j",
    async (policies) => {
      const user = setupUser();
      const { onSave } = await renderEditor(policies);
      expectValidSelection("Default");
      await user.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledWith({}, policies));
    }
  );

  it("shows readable custom overrides and preserves them when selected", async () => {
    const user = setupUser();
    const { onSave } = await renderEditor({ write: "DENY" });
    expectValidSelection("Custom");
    await user.click(screen.getByRole("combobox"));
    const option = screen.getByRole("option", { name: "Custom" });
    expect(option).not.toHaveAttribute("aria-disabled", "true");
    fireEvent.click(option);
    expectValidSelection("Custom");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({}, { write: "DENY" })
    );
  });

  it("shows Default for the shared MCP editor's all-Ask defaults", async () => {
    await renderEditor(
      {},
      ITEMS.map((item) => ({ ...item, defaultPolicy: "ASK" }))
    );
    expectValidSelection("Default");
  });

  it.each(["ALWAYS", "ASK"] as const)(
    "shows a uniform %s override",
    async (policy) => {
      await renderEditor({ read: policy, write: policy });
      expectValidSelection(policy === "ALWAYS" ? "Auto-approve" : "Ask");
    }
  );

  it("restores registry defaults after a bulk override", async () => {
    const user = setupUser();
    const { onSave } = await renderEditor();
    await user.click(screen.getByRole("combobox"));
    expect(
      screen.queryByRole("option", { name: "Custom" })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "Auto-approve" }));
    expectValidSelection("Auto-approve");
    await user.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Default" }));
    expectValidSelection("Default");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({}, { read: "ALWAYS", write: "ASK" })
    );
  });
});
