import React from "react";
import { fireEvent, screen } from "@testing-library/react";
import { render } from "@tests/setup/test-utils";
import BaseInputBar from "@/sections/input/BaseInputBar";

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
