import { act, render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useRef } from "react";
import {
  useContentEditable,
  type UseContentEditableReturn,
} from "@/hooks/useContentEditable";

let api: UseContentEditableReturn;

interface HarnessProps {
  pasteTilesEnabled?: boolean;
}

function Harness({ pasteTilesEnabled = false }: HarnessProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  api = useContentEditable({ wrapperRef, pasteTilesEnabled });
  return (
    <div ref={wrapperRef}>
      <div
        ref={api.ref}
        contentEditable
        suppressContentEditableWarning
        data-testid="editable"
        onInput={api.handleInput}
        onCompositionStart={api.handleCompositionStart}
        onCompositionEnd={api.handleCompositionEnd}
      />
    </div>
  );
}

function input(): HTMLDivElement {
  return api.ref.current as HTMLDivElement;
}

function caretToEnd(): void {
  const sel = window.getSelection()!;
  const r = document.createRange();
  r.selectNodeContents(input());
  r.collapse(false);
  sel.removeAllRanges();
  sel.addRange(r);
}

function fireBeforeInput(inputType: string): boolean {
  let event: Event;
  try {
    event = new InputEvent("beforeinput", {
      inputType,
      bubbles: true,
      cancelable: true,
    });
    if ((event as InputEvent).inputType !== inputType) {
      throw new Error("jsdom InputEvent lacks inputType");
    }
  } catch {
    event = new Event("beforeinput", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "inputType", { value: inputType });
  }
  return input().dispatchEvent(event);
}

/** Simulate one natively-typed keystroke (beforeinput → DOM edit → input). */
function typeText(text: string): void {
  act(() => {
    fireBeforeInput("insertText");
    input().appendChild(document.createTextNode(text));
    input().normalize();
    caretToEnd();
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function pressKey(init: KeyboardEventInit): boolean {
  let allowed = true;
  act(() => {
    allowed = input().dispatchEvent(
      new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init })
    );
  });
  return allowed;
}

const undo = () => pressKey({ key: "z", metaKey: true });
const redo = () => pressKey({ key: "z", metaKey: true, shiftKey: true });

describe("useContentEditable undo/redo", () => {
  let now: number;

  beforeEach(() => {
    now = 1_000_000;
    jest.spyOn(Date, "now").mockImplementation(() => now);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  function advance(ms: number): void {
    now += ms;
  }

  it("undoes a paste without touching previously typed text", () => {
    render(<Harness />);
    typeText("hello ");
    advance(2000);
    act(() => api.pasteText("PASTED-WRONG-THING"));
    expect(input().textContent).toBe("hello PASTED-WRONG-THING");

    undo();
    expect(input().textContent).toBe("hello ");
    expect(api.message).toBe("hello ");

    undo();
    expect(input().textContent).toBe("");
    expect(api.message).toBe("");
  });

  it("redoes undone edits", () => {
    render(<Harness />);
    typeText("draft");
    advance(2000);
    act(() => api.pasteText(" plus paste"));

    undo();
    undo();
    expect(input().textContent).toBe("");

    redo();
    expect(input().textContent).toBe("draft");
    redo();
    expect(input().textContent).toBe("draft plus paste");
  });

  it("supports ctrl+y as redo", () => {
    render(<Harness />);
    typeText("abc");
    undo();
    expect(input().textContent).toBe("");
    pressKey({ key: "y", ctrlKey: true });
    expect(input().textContent).toBe("abc");
  });

  it("coalesces a typing burst into one undo unit, split by pauses", () => {
    render(<Harness />);
    typeText("a");
    typeText("b");
    typeText("c");
    advance(2000);
    typeText("d");
    typeText("e");
    expect(input().textContent).toBe("abcde");

    undo();
    expect(input().textContent).toBe("abc");
    undo();
    expect(input().textContent).toBe("");
  });

  it("treats insert and delete bursts as separate undo units", () => {
    render(<Harness />);
    typeText("abcd");
    act(() => {
      fireBeforeInput("deleteContentBackward");
      const node = input().firstChild as Text;
      node.textContent = "abc";
      caretToEnd();
      input().dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(input().textContent).toBe("abc");

    undo();
    expect(input().textContent).toBe("abcd");
    undo();
    expect(input().textContent).toBe("");
  });

  it("always consumes cmd+z, even with empty history", () => {
    render(<Harness />);
    const allowed = pressKey({ key: "z", metaKey: true });
    expect(allowed).toBe(false); // preventDefault — native undo must never run
    expect(input().textContent).toBe("");
  });

  it("handles historyUndo/historyRedo beforeinput (menu undo)", () => {
    render(<Harness />);
    typeText("typed");
    advance(2000);
    act(() => api.pasteText("PASTE"));

    let allowed = true;
    act(() => {
      allowed = fireBeforeInput("historyUndo");
    });
    expect(allowed).toBe(false);
    expect(input().textContent).toBe("typed");

    act(() => {
      fireBeforeInput("historyRedo");
    });
    expect(input().textContent).toBe("typedPASTE");
  });

  it("undoes a paste-tile insertion entirely", () => {
    render(<Harness pasteTilesEnabled />);
    typeText("note ");
    advance(2000);
    const longText = "line1\nline2\nline3\nline4\nline5";
    act(() => api.pasteText(longText));
    expect(input().querySelector("[data-rich-tile]")).not.toBeNull();
    expect(api.message).toBe("note " + longText);

    undo();
    expect(input().querySelector("[data-rich-tile]")).toBeNull();
    expect(api.message).toBe("note ");
  });

  it("restores a tile removed via its remove button", () => {
    render(<Harness pasteTilesEnabled />);
    const longText = "line1\nline2\nline3\nline4\nline5";
    act(() => api.pasteText(longText));
    const tile = input().querySelector("[data-rich-tile]");
    expect(tile).not.toBeNull();

    act(() => {
      const removeBtn = tile!.querySelector("[data-rich-tile-remove]")!;
      const event = new MouseEvent("mousedown", {
        bubbles: true,
        cancelable: true,
      });
      Object.defineProperty(event, "target", { value: removeBtn });
      // Tile removal is delegated through the host's onMouseDown handler.
      api.handleTileMouseDown(
        event as unknown as React.MouseEvent<HTMLDivElement>
      );
    });
    expect(input().querySelector("[data-rich-tile]")).toBeNull();

    undo();
    expect(input().querySelector("[data-rich-tile]")).not.toBeNull();
    expect(api.message).toBe(longText);
  });

  it("clears history on clearMessage (submit)", () => {
    render(<Harness />);
    typeText("sent message");
    act(() => api.clearMessage());
    expect(input().textContent).toBe("");

    undo();
    expect(input().textContent).toBe("");
    expect(api.message).toBe("");
  });

  it("makes setMessage (draft restore / queue edit) undoable", () => {
    render(<Harness />);
    typeText("original");
    advance(2000);
    act(() => api.setMessage("replaced"));
    expect(input().textContent).toBe("replaced");

    undo();
    expect(input().textContent).toBe("original");
  });

  it("new edits after undo clear the redo stack", () => {
    render(<Harness />);
    typeText("first");
    advance(2000);
    typeText("second");
    undo();
    expect(input().textContent).toBe("first");

    advance(2000);
    typeText("third");
    redo();
    expect(input().textContent).toBe("firstthird");
  });
});
