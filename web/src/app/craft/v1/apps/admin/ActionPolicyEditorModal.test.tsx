/** @jest-environment jsdom */

import {
  within,
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
      description="Configure this app for Craft."
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
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  return { onSave };
}

test("keeps saved overrides when saving without an edit", async () => {
  const { onSave } = await renderEditor({ write: "DENY" });
  expect(
    within(screen.getByRole("group", { name: "Write" })).getByRole("button", {
      name: "Disabled",
    })
  ).toHaveAttribute("aria-pressed", "true");
  await setupUser().click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(onSave).toHaveBeenCalledWith({}, { write: "DENY" })
  );
});

test("restores registry defaults after a bulk override", async () => {
  const { onSave } = await renderEditor();
  const user = setupUser();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{Enter}");
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(onSave).toHaveBeenCalledWith({}, { read: "ALWAYS", write: "ASK" })
  );
});
