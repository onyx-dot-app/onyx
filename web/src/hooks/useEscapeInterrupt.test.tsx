import { act, cleanup, renderHook } from "@testing-library/react";
import { useEscapeInterrupt } from "@/hooks/useEscapeInterrupt";

function escapeEvent(init: KeyboardEventInit = {}): KeyboardEvent {
  return new KeyboardEvent("keydown", {
    key: "Escape",
    bubbles: true,
    cancelable: true,
    ...init,
  });
}

function dispatchEscape(event = escapeEvent()): KeyboardEvent {
  act(() => {
    document.body.dispatchEvent(event);
  });
  return event;
}

function visibleLayer(
  role: "dialog" | "alertdialog" | "menu" | "listbox"
): HTMLElement {
  const layer = document.createElement("div");
  layer.setAttribute("role", role);
  Object.defineProperty(layer, "getClientRects", {
    value: () => [{ width: 1, height: 1 }],
  });
  document.body.appendChild(layer);
  return layer;
}

describe("useEscapeInterrupt", () => {
  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
  });

  it("interrupts on a single unhandled Escape", () => {
    const onInterrupt = jest.fn();
    renderHook(() => useEscapeInterrupt({ enabled: true, onInterrupt }));

    const event = dispatchEscape();

    expect(onInterrupt).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not interrupt while disabled", () => {
    const onInterrupt = jest.fn();
    renderHook(() => useEscapeInterrupt({ enabled: false, onInterrupt }));

    dispatchEscape();

    expect(onInterrupt).not.toHaveBeenCalled();
  });

  it("ignores repeated Escape keydown events", () => {
    const onInterrupt = jest.fn();
    renderHook(() => useEscapeInterrupt({ enabled: true, onInterrupt }));

    dispatchEscape(escapeEvent({ repeat: true }));

    expect(onInterrupt).not.toHaveBeenCalled();
  });

  it("does not interrupt when Escape was already handled", () => {
    const onInterrupt = jest.fn();
    renderHook(() => useEscapeInterrupt({ enabled: true, onInterrupt }));
    const event = escapeEvent();
    event.preventDefault();

    dispatchEscape(event);

    expect(onInterrupt).not.toHaveBeenCalled();
  });

  it("does not interrupt when another capture handler handles Escape", () => {
    const onInterrupt = jest.fn();
    renderHook(() => useEscapeInterrupt({ enabled: true, onInterrupt }));

    function handleEscape(event: KeyboardEvent) {
      event.preventDefault();
    }
    document.addEventListener("keydown", handleEscape, true);
    const event = dispatchEscape();
    document.removeEventListener("keydown", handleEscape, true);

    expect(onInterrupt).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(true);
  });

  it.each(["dialog", "alertdialog", "menu", "listbox"] as const)(
    "lets visible %s layers reserve Escape",
    (role) => {
      const onInterrupt = jest.fn();
      visibleLayer(role);
      renderHook(() => useEscapeInterrupt({ enabled: true, onInterrupt }));

      const event = dispatchEscape();

      expect(onInterrupt).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(false);
    }
  );

  it("does not interrupt when a visible layer closes before the bubble listener", () => {
    const onInterrupt = jest.fn();
    const layer = visibleLayer("dialog");
    renderHook(() => useEscapeInterrupt({ enabled: true, onInterrupt }));

    function closeLayer() {
      layer.remove();
    }
    document.addEventListener("keydown", closeLayer, true);
    const event = dispatchEscape();
    document.removeEventListener("keydown", closeLayer, true);

    expect(onInterrupt).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });
});
