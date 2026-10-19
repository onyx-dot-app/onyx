import { useState } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
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
  await setupUser().click(screen.getByRole("button", { name: "Disabled" }));
  expect(screen.getByRole("button", { name: "Disabled" })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
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
  await user.click(screen.getByRole("combobox"));
  await user.click(screen.getByRole("option", { name: /Default/i }));
  expect(onChange).toHaveBeenCalledWith({
    read: "ALWAYS",
    write: "ASK",
    other: "ASK",
  });
});
