import { useState } from "react";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import PolicyEditor from "@/sections/actions/PolicyEditor";
import type { PolicyValue } from "@/lib/integrations/types";

function Editor() {
  const [policies, setPolicies] = useState<Record<string, PolicyValue>>({});
  return (
    <PolicyEditor
      items={[
        {
          id: "search",
          name: "Search messages",
          description: "Find workspace messages.",
          defaultPolicy: "ask",
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
      { name: "Blocked" }
    )
  );
  expect(
    within(screen.getByRole("group", { name: "Search messages" })).getByRole(
      "button",
      { name: "Blocked" }
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
          defaultPolicy: "allow",
        },
        {
          id: "write",
          name: "Write",
          description: "Write data",
          defaultPolicy: "ask",
        },
      ]}
      policies={{ read: "blocked", write: "blocked", other: "ask" }}
      onChange={onChange}
    />
  );
  const user = setupUser();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith({
    read: "allow",
    write: "ask",
    other: "ask",
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
          defaultPolicy: "ask",
        },
        {
          id: "blocked",
          name: "Read secrets",
          description: "",
          defaultPolicy: "blocked",
          editable: false,
          lockReason: "workspace_disabled",
        },
        {
          id: "write",
          name: "Write data",
          description: "",
          defaultPolicy: "ask",
        },
      ]}
      policies={{ read: "ask", blocked: "blocked", write: "ask" }}
      onChange={onChange}
      onReset={onReset}
    />
  );
  const user = setupUser();
  await user.type(
    screen.getByRole("searchbox", { name: "Search tools" }),
    "Read"
  );
  expect(
    within(screen.getByRole("group", { name: "Read secrets" })).getByRole(
      "button",
      { name: "Allow" }
    )
  ).toBeDisabled();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith({
    read: "allow",
    blocked: "blocked",
    write: "ask",
  });
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  expect(onReset).toHaveBeenCalledTimes(1);
});
