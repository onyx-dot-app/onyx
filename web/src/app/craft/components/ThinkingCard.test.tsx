import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import ThinkingCard from "@/app/craft/components/ThinkingCard";

jest.mock("@/components/chat/MinimalMarkdown", () => ({
  __esModule: true,
  default: ({ content }: { content: string }) => <div>{content}</div>,
}));

describe("ThinkingCard", () => {
  it("does not reset a manual disclosure choice when defaultOpen changes", () => {
    const { rerender } = render(
      <ThinkingCard
        content="Inspecting the stream."
        isStreaming={false}
        defaultOpen
      />
    );

    expect(screen.getByText("Inspecting the stream.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Thinking/ }));
    expect(
      screen.queryByText("Inspecting the stream.")
    ).not.toBeInTheDocument();

    rerender(
      <ThinkingCard
        content="Inspecting the stream."
        isStreaming={false}
        defaultOpen={false}
      />
    );
    rerender(
      <ThinkingCard
        content="Inspecting the stream."
        isStreaming={false}
        defaultOpen
      />
    );

    expect(
      screen.queryByText("Inspecting the stream.")
    ).not.toBeInTheDocument();
  });
});
