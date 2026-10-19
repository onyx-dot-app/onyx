import { useState } from "react";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import PolicyEditor from "@/sections/actions/PolicyEditor";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

function Editor() {
  const [policies, setPolicies] = useState<Record<string, ActionPolicy>>({});
  return (
    <PolicyEditor
      items={[
        {
          id: "search",
          name: "Search messages",
          description: "Find workspace messages.",
          defaultPolicy: "ASK",
        },
      ]}
      policies={policies}
      onChange={setPolicies}
    />
  );
}

test("shows per-action permissions immediately without an Advanced disclosure", async () => {
  render(<Editor />);
  expect(screen.getByText("Search messages")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Advanced/ })
  ).not.toBeInTheDocument();
  await setupUser().click(
    within(screen.getByRole("group", { name: "Search messages" })).getByRole(
      "button",
      { name: "Disabled" }
    )
  );
  expect(
    within(screen.getByRole("group", { name: "Search messages" })).getByRole(
      "button",
      { name: "Disabled" }
    )
  ).toHaveAttribute("aria-pressed", "true");
});

test("restores each action's default without changing policies outside the list", async () => {
  const onChange = jest.fn();
  render(
    <PolicyEditor
      items={[
        {
          id: "read",
          name: "Read",
          description: "Read data",
          defaultPolicy: "ALWAYS",
        },
        {
          id: "write",
          name: "Write",
          description: "Write data",
          defaultPolicy: "ASK",
        },
      ]}
      policies={{ read: "DENY", write: "DENY", other: "ASK" }}
      onChange={onChange}
    />
  );
  const user = setupUser();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith({
    read: "ALWAYS",
    write: "ASK",
    other: "ASK",
  });
});

test("bulk changes only matching editable actions and reset delegates to the owner", async () => {
  const onChange = jest.fn();
  const onReset = jest.fn();
  render(
    <PolicyEditor
      items={[
        {
          id: "read",
          name: "Read data",
          description: "",
          defaultPolicy: "ASK",
        },
        {
          id: "blocked",
          name: "Read secrets",
          description: "",
          defaultPolicy: "DENY",
          editable: false,
          lockReason: "workspace_disabled",
        },
        {
          id: "write",
          name: "Write data",
          description: "",
          defaultPolicy: "ASK",
        },
      ]}
      policies={{ read: "ASK", blocked: "DENY", write: "ASK" }}
      onChange={onChange}
      onReset={onReset}
    />
  );
  const user = setupUser();
  await user.type(
    screen.getByRole("textbox", { name: "Search tools" }),
    "Read"
  );
  expect(
    within(screen.getByRole("group", { name: "Read secrets" })).getByRole(
      "button",
      { name: "Auto-approve" }
    )
  ).toBeDisabled();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith({
    read: "ALWAYS",
    blocked: "DENY",
    write: "ASK",
  });
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  expect(onReset).toHaveBeenCalledTimes(1);
});
