import { render, screen } from "@tests/setup/test-utils";
import BaseInputBar from "@/sections/input/BaseInputBar";
import type { QueuedMessage } from "@/app/app/interfaces";

const queuedMessages: QueuedMessage[] = [
  { id: 1, text: "Write a follow-up Playwright smoke test" },
];

describe("BaseInputBar pre-input stack", () => {
  it("renders the above-input slot before queued messages", () => {
    render(
      <BaseInputBar
        onSubmit={jest.fn()}
        isRunning
        queuedMessages={queuedMessages}
        onQueueMessage={jest.fn()}
        onRemoveQueuedMessage={jest.fn()}
        aboveInputSlot={
          <div data-testid="approval-slot">Approval required</div>
        }
      />
    );

    const approvalSlot = screen.getByTestId("approval-slot");
    const queuedMessage = screen.getByTestId("queued-message-bar");
    const position = approvalSlot.compareDocumentPosition(queuedMessage);

    expect(Boolean(position & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  });
});
