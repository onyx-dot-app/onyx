import { fireEvent, renderHook } from "@tests/setup/test-utils";
import { useHotkey } from "@opal/hooks";

function setUserAgent(userAgent: string) {
  Object.defineProperty(window.navigator, "userAgent", {
    value: userAgent,
    configurable: true,
  });
}

describe("useHotkey", () => {
  afterEach(() => setUserAgent("jsdom"));

  it("matches ⌘⌥1 on macOS by its physical key", () => {
    setUserAgent("Macintosh");
    const handler = jest.fn();
    renderHook(() => useHotkey("mod+alt+1", handler));
    fireEvent.keyDown(document, {
      key: "¡",
      code: "Digit1",
      metaKey: true,
      altKey: true,
    });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("matches Ctrl+Alt+1 elsewhere by its key", () => {
    setUserAgent("Windows");
    const handler = jest.fn();
    renderHook(() => useHotkey("mod+alt+1", handler));
    fireEvent.keyDown(document, {
      key: "1",
      code: "Digit1",
      ctrlKey: true,
      altKey: true,
    });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("matches Ctrl+Option+1 on macOS by its physical key", () => {
    setUserAgent("Macintosh");
    const handler = jest.fn();
    renderHook(() => useHotkey("ctrl+alt+1", handler));
    fireEvent.keyDown(document, {
      key: "¡",
      code: "Digit1",
      ctrlKey: true,
      altKey: true,
    });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("ignores an AltGr character on its digit key", () => {
    setUserAgent("Windows");
    const handler = jest.fn();
    renderHook(() => useHotkey("mod+alt+7", handler));
    fireEvent.keyDown(document, {
      key: "{",
      code: "Digit7",
      ctrlKey: true,
      altKey: true,
    });
    expect(handler).not.toHaveBeenCalled();
  });
});
