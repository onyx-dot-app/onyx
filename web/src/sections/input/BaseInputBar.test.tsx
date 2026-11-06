import React from "react";
import { fireEvent, screen } from "@testing-library/react";
import { render, setupUser } from "@tests/setup/test-utils";
import BaseInputBar from "@/sections/input/BaseInputBar";

it("preserves the draft and blocks typing and submission until enabled", async () => {
  const user = setupUser();
  const onSubmit = jest.fn();
  const { rerender } = render(
    <BaseInputBar onSubmit={onSubmit} isRunning={false} />
  );
  const input = screen.getByRole("textbox", { name: "Message input" });
  input.textContent = "Keep this draft";
  fireEvent.input(input);

  rerender(<BaseInputBar onSubmit={onSubmit} isRunning={false} disabled />);
  expect(input).toHaveAttribute("contenteditable", "false");
  await user.type(input, "unwanted text{Enter}");
  expect(input.textContent).toBe("Keep this draft");
  expect(onSubmit).not.toHaveBeenCalled();

  rerender(<BaseInputBar onSubmit={onSubmit} isRunning={false} />);
  expect(input).toHaveAttribute("contenteditable", "true");
  await user.click(input);
  await user.keyboard("{Enter}");
  expect(onSubmit).toHaveBeenCalledWith("Keep this draft");
});

describe("BaseInputBar queue handoff", () => {
  it.each([
    { outcome: false, retained: true },
    { outcome: true, retained: false },
    { outcome: undefined, retained: false },
  ])(
    "retains draft only when queue rejects with $outcome",
    ({ outcome, retained }) => {
      const onQueueMessage = jest.fn(() => outcome);
      const onSubmit = jest.fn();
      render(
        <BaseInputBar
          onSubmit={onSubmit}
          isRunning
          onQueueMessage={onQueueMessage}
        />
      );
      const input = screen.getByRole("textbox", { name: "Message input" });
      input.textContent = "Keep this draft";
      fireEvent.input(input);
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onQueueMessage).toHaveBeenCalledWith("Keep this draft");
      expect(onSubmit).not.toHaveBeenCalled();
      expect(input.textContent).toBe(retained ? "Keep this draft" : "");
    }
  );
});
