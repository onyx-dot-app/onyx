import { useState } from "react";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import PolicyEditor from "@/sections/actions/PolicyEditor";
import type { PolicyValue } from "@/lib/integrations/types";

function Editor() {
  const [policies, setPolicies] = useState<Record<string, PolicyValue>>({});
  return (
    <PolicyEditor
      title="Actions"
      resetLabel="Use defaults"
      onReset={jest.fn()}
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

test("bulk changes only the actions that accept the value and reset delegates to the owner", async () => {
  const onChange = jest.fn();
  const onReset = jest.fn();
  render(
    <PolicyEditor
      title="Actions"
      resetLabel="Use defaults"
      items={[
        {
          id: "read",
          name: "Read data",
          description: "",
          defaultPolicy: "ask",
        },
        {
          id: "secrets",
          name: "Read secrets",
          description: "",
          defaultPolicy: "ask",
          disabledPolicies: ["allow"],
        },
      ]}
      policies={{ read: "ask", secrets: "ask" }}
      onChange={onChange}
      onReset={onReset}
    />
  );
  const user = setupUser();
  expect(
    within(screen.getByRole("group", { name: "Read secrets" })).getByRole(
      "button",
      { name: "Allow" }
    )
  ).toBeDisabled();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith({ read: "allow", secrets: "ask" });
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  expect(onReset).toHaveBeenCalledTimes(1);
});
