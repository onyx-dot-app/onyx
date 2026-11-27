import { useState } from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SkillContentsTab from "@/sections/customize/SkillContentsTab";
import type { SkillEditableDetail } from "@/lib/skills/types";

const mockPatchUserSkill = jest.fn();
const mockRemoveUserSkillFile = jest.fn();
jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  patchUserSkill: (...args: unknown[]) => mockPatchUserSkill(...args),
  removeUserSkillFile: (...args: unknown[]) => mockRemoveUserSkillFile(...args),
}));

const detail = {
  id: "skill-id",
  name: "report-writer",
  description: "Writes reports",
  instructions_markdown: "Write the report.",
  current_version_id: "v1",
  files: [{ path: "notes.md", size: 4 }],
} as SkillEditableDetail;

function Harness({ onSaved }: { onSaved: () => Promise<boolean> }) {
  const [editing, setEditing] = useState(false);
  return (
    <SkillContentsTab
      name={detail.name}
      description={detail.description}
      versionNumber={1}
      instructions={detail.instructions_markdown}
      files={detail.files}
      detail={detail}
      editing={editing}
      onEditingChange={setEditing}
      onDirtyChange={() => {}}
      confirmLeave={(leave) => leave()}
      onSaved={onSaved}
    />
  );
}

describe("SkillContentsTab partial save", () => {
  beforeEach(() => {
    mockPatchUserSkill.mockReset();
    mockRemoveUserSkillFile.mockReset();
  });

  it("reloads the saved version after a later step fails, and retries only the rest from it", async () => {
    const user = setupUser();
    const onSaved = jest.fn().mockResolvedValue(true);
    mockPatchUserSkill.mockResolvedValue({ current_version_id: "v2" });
    mockRemoveUserSkillFile
      .mockRejectedValueOnce(new Error("Remove failed"))
      .mockResolvedValueOnce({ current_version_id: "v3" });

    render(<Harness onSaved={onSaved} />);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const editor = screen.getByRole("textbox", { name: "SKILL.md" });
    await user.clear(editor);
    await user.click(editor);
    await user.paste(
      '---\nname: "report-writer"\ndescription: "Writes better reports"\n---\n\nWrite the report.'
    );
    await user.click(screen.getByRole("button", { name: "notes.md" }));
    await user.click(screen.getByRole("button", { name: "Remove notes.md" }));
    await user.click(screen.getByRole("button", { name: "Save Version" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(mockRemoveUserSkillFile).toHaveBeenCalledWith(
      "skill-id",
      "notes.md",
      "v2"
    );

    await user.click(screen.getByRole("button", { name: "Save Version" }));
    await waitFor(() =>
      expect(mockRemoveUserSkillFile).toHaveBeenCalledTimes(2)
    );
    expect(mockPatchUserSkill).toHaveBeenCalledTimes(1);
    expect(mockRemoveUserSkillFile).toHaveBeenLastCalledWith(
      "skill-id",
      "notes.md",
      "v2"
    );
  });
});
