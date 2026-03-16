import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { useIsStreaming, useTriggerAction } from "./hooks";
import { StreamingContext, ActionContext } from "./context";

function StreamingIndicator() {
  const isStreaming = useIsStreaming();
  return <span data-testid="streaming">{isStreaming ? "yes" : "no"}</span>;
}

function ActionButton({ actionId }: { actionId: string }) {
  const trigger = useTriggerAction();
  return (
    <button
      data-testid="action-btn"
      onClick={() => trigger(actionId, { extra: "data" })}
    >
      Fire
    </button>
  );
}

describe("useIsStreaming", () => {
  it("returns false by default", () => {
    render(<StreamingIndicator />);
    expect(screen.getByTestId("streaming")).toHaveTextContent("no");
  });

  it("returns true when streaming context is true", () => {
    render(
      <StreamingContext.Provider value={{ isStreaming: true }}>
        <StreamingIndicator />
      </StreamingContext.Provider>
    );
    expect(screen.getByTestId("streaming")).toHaveTextContent("yes");
  });

  it("returns false when streaming context is false", () => {
    render(
      <StreamingContext.Provider value={{ isStreaming: false }}>
        <StreamingIndicator />
      </StreamingContext.Provider>
    );
    expect(screen.getByTestId("streaming")).toHaveTextContent("no");
  });
});

describe("useTriggerAction", () => {
  it("calls action handler with actionId and payload", () => {
    const handler = vi.fn();

    render(
      <ActionContext.Provider value={handler}>
        <ActionButton actionId="test-action" />
      </ActionContext.Provider>
    );

    fireEvent.click(screen.getByTestId("action-btn"));

    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith({
      actionId: "test-action",
      payload: { extra: "data" },
    });
  });

  it("does nothing when no action handler is provided", () => {
    // Should not throw
    render(
      <ActionContext.Provider value={null}>
        <ActionButton actionId="orphan" />
      </ActionContext.Provider>
    );

    expect(() => {
      fireEvent.click(screen.getByTestId("action-btn"));
    }).not.toThrow();
  });
});
