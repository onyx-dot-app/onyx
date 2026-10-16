/** @jest-environment jsdom */

import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
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
    fallbackPolicy: "ALWAYS",
  },
  {
    id: "write",
    name: "Write",
    description: "Write tickets",
    fallbackPolicy: "ASK",
  },
];

function renderEditor(
  initialPolicies: Record<string, ActionPolicy> = {},
  items: PolicyEditorItem[] = ITEMS
) {
  const onSave = jest.fn().mockResolvedValue(undefined);
  render(
    <ActionPolicyEditorModal
      onClose={jest.fn()}
      title="App settings"
      description="Configure this app"
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
  return { onSave };
}

describe("ActionPolicyEditorModal approval settings", () => {
  it("preserves initial choices when setup saves without an edit", async () => {
    const user = setupUser();
    const { onSave } = renderEditor({ write: "DENY" });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({}, { write: "DENY" })
    );
  });

  it("applies bulk edits only to matching actions and resets all actions", async () => {
    const user = setupUser();
    const { onSave } = renderEditor();
    await user.type(
      screen.getByRole("textbox", { name: "Search actions" }),
      "Write"
    );
    await user.click(
      screen.getAllByRole("button", { name: "Auto-approve" })[0]!
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({}, { write: "ALWAYS" })
    );
    await user.click(
      screen.getByRole("button", { name: "Reset all to defaults" })
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        {},
        { read: "ALWAYS", write: "ASK" }
      )
    );
  });
});
