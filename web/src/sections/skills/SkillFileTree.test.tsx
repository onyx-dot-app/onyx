import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import SkillFileTree from "@/sections/skills/SkillFileTree";

function getVisibleText(text: string): HTMLElement {
  const element = screen
    .getAllByText(text)
    .find((candidate) => !candidate.closest("[aria-hidden='true']"));
  if (!element) throw new Error(`No visible element found for "${text}".`);
  return element;
}

describe("SkillFileTree", () => {
  it("groups paths into expandable folders and sorts folders before files", async () => {
    const user = userEvent.setup();
    render(
      <SkillFileTree
        files={[
          { path: "z.txt", size: 10 },
          { path: "scripts/run.py", size: 20 },
          { path: "scripts/lib/util.py", size: 30 },
          { path: "a.txt", size: 40 },
        ]}
      />
    );

    const scripts = screen.getByRole("button", { name: /scripts/i });
    const firstFile = getVisibleText("a.txt");
    const lastFile = getVisibleText("z.txt");
    expect(
      scripts.compareDocumentPosition(firstFile) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      firstFile.compareDocumentPosition(lastFile) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(screen.queryByText("run.py")).not.toBeInTheDocument();

    await user.click(scripts);
    expect(screen.getAllByText("run.py")).not.toHaveLength(0);
    expect(screen.getByText("20 Bytes")).toBeInTheDocument();
    expect(screen.queryByText("util.py")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /lib/i }));
    expect(screen.getAllByText("util.py")).not.toHaveLength(0);
  });

  it("removes the selected file by its full bundle path", async () => {
    const user = userEvent.setup();
    const onRemove = jest.fn();
    render(
      <TooltipProvider>
        <SkillFileTree
          files={[{ path: "scripts/run.py", size: 20 }]}
          onRemove={onRemove}
        />
      </TooltipProvider>
    );

    await user.click(screen.getByRole("button", { name: /scripts/i }));
    await user.click(screen.getByRole("button", { name: "Remove run.py" }));

    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith("scripts/run.py");
  });
});
