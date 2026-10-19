/** @jest-environment jsdom */

import { useState } from "react";
import { InputTypeIn } from "@opal/components";
import { fireEvent, render, screen } from "@tests/setup/test-utils";
import CraftAppEditorTabs from "@/sections/plugins/CraftAppEditorTabs";

function DraftField() {
  const [draft, setDraft] = useState("");
  return (
    <InputTypeIn
      aria-label="Draft"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
    />
  );
}

function Editor() {
  const [tab, setTab] = useState("configuration");
  return (
    <CraftAppEditorTabs
      value={tab}
      onValueChange={setTab}
      configuration={<DraftField />}
      permissions={<InputTypeIn aria-label="Permission" />}
    />
  );
}

describe("CraftAppEditorTabs", () => {
  it("shows only provided sections and preserves local drafts across tabs", () => {
    render(<Editor />);
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(
      screen.queryByRole("tab", { name: "Authentication" })
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Draft" }), {
      target: { value: "unsaved name" },
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Permissions" }), {
      button: 0,
    });
    expect(
      screen.queryByRole("textbox", { name: "Draft" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Permission" })).toBeVisible();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Configuration" }), {
      button: 0,
    });
    expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue(
      "unsaved name"
    );
  });

  it("disables navigation while the parent saves", () => {
    render(
      <CraftAppEditorTabs
        value="configuration"
        onValueChange={jest.fn()}
        configuration={<DraftField />}
        skills={<InputTypeIn aria-label="Skill" />}
        busy
      />
    );
    for (const tab of screen.getAllByRole("tab")) expect(tab).toBeDisabled();
  });

  it("shows configuration directly when no other sections exist", () => {
    render(
      <CraftAppEditorTabs
        value="configuration"
        onValueChange={jest.fn()}
        configuration={<DraftField />}
      />
    );
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Draft" })).toBeVisible();
  });
});
