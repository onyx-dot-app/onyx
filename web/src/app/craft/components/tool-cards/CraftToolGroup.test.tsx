import React from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import CraftToolGroup from "@/app/craft/components/tool-cards/CraftToolGroup";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const failedCall: ToolCallState = {
  id: "failed-call",
  kind: "other",
  title: "Look up a document",
  description: "",
  command: "",
  status: "failed",
  rawOutput: "The document could not be found.",
};

describe("CraftToolGroup", () => {
  it("keeps failed details collapsed until the user expands them", async () => {
    const user: ReturnType<typeof setupUser> = setupUser();
    render(<CraftToolGroup toolCalls={[failedCall]} />);

    const group: HTMLElement = screen.getByRole("button", { name: /Working/ });
    expect(group).toHaveTextContent("1 call");
    expect(group).not.toHaveTextContent(/failed/i);
    await user.click(group);

    const call: HTMLElement = screen.getByRole("button", {
      name: failedCall.title,
    });
    expect(call).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(failedCall.rawOutput)).not.toBeInTheDocument();

    await user.click(call);
    expect(screen.getByText(failedCall.rawOutput)).toBeVisible();
  });

  it("keeps a newly appended failure collapsed in an active group", () => {
    const activeCall: ToolCallState = {
      ...failedCall,
      id: "active-call",
      title: "Look up another document",
      status: "in_progress",
      rawOutput: "",
    };
    const { rerender }: ReturnType<typeof render> = render(
      <CraftToolGroup toolCalls={[activeCall]} />
    );

    rerender(<CraftToolGroup toolCalls={[activeCall, failedCall]} />);

    expect(
      screen.getByRole("button", { name: failedCall.title })
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(failedCall.rawOutput)).not.toBeInTheDocument();
  });

  it("still shows standalone failure details by default", () => {
    render(<CraftToolCard toolCall={failedCall} />);

    expect(screen.getByText(failedCall.rawOutput)).toBeVisible();
  });
});
