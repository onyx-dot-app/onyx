import { act, renderHook } from "@testing-library/react";
import type { KeyboardEvent } from "react";
import { useQueuedMessageNavigation } from "@/hooks/useQueuedMessageNavigation";
import type { PendingChatMessage } from "@/lib/chat/types";

const messages: PendingChatMessage[] = [
  { id: "queued", message: "Queued", delivery: "queue", target_response_id: 2 },
];

function keyDown(key: string): KeyboardEvent<HTMLDivElement> {
  const event: Pick<KeyboardEvent<HTMLDivElement>, "key" | "preventDefault"> = {
    key,
    preventDefault: jest.fn(),
  };
  return event as KeyboardEvent<HTMLDivElement>;
}

test("text that reaches the composer without a key ends queue navigation", () => {
  const onSendNow = jest.fn();
  const onRemove = jest.fn();
  const { result, rerender } = renderHook(
    ({ inputIsEmpty }) =>
      useQueuedMessageNavigation({
        messages,
        inputIsEmpty,
        onRemove,
        onEdit: jest.fn(),
        onSendNow,
      }),
    { initialProps: { inputIsEmpty: true } }
  );
  act(() => {
    result.current.handleKeyDown(keyDown("ArrowUp"));
  });
  expect(result.current.highlightedId).toBe("queued");

  // A context-menu paste or dictation adds text without a keydown.
  rerender({ inputIsEmpty: false });
  expect(result.current.highlightedId).toBeNull();
  let consumed = true;
  act(() => {
    consumed = result.current.handleKeyDown(keyDown("Enter"));
  });
  expect(consumed).toBe(false);
  act(() => {
    consumed = result.current.handleKeyDown(keyDown("Backspace"));
  });
  expect(consumed).toBe(false);
  expect(onSendNow).not.toHaveBeenCalled();
  expect(onRemove).not.toHaveBeenCalled();
});
