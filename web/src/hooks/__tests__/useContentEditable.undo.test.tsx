import { act, render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useRef } from "react";
import {
  useContentEditable,
  type UseContentEditableReturn,
} from "@/hooks/useContentEditable";
import {
  pushBoundedSnapshot,
  MAX_UNDO_ENTRIES,
  MAX_UNDO_TOTAL_CHARS,
  type EditableSnapshot,
} from "@/lib/contentEditable";

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

/** Collapsed-caret offset in text units from the start of the input. */
function flatCaret(): number | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) return null;
  const r = document.createRange();
  r.selectNodeContents(input());
  const caret = sel.getRangeAt(0);
  r.setEnd(caret.startContainer, caret.startOffset);
  return r.toString().length;
}

function caretAtTextOffset(offset: number): void {
  const node = input().firstChild as Text;
  const sel = window.getSelection()!;
  const r = document.createRange();
  r.setStart(node, offset);
  r.collapse(true);
  sel.removeAllRanges();
  sel.addRange(r);
}

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

  it("restores the caret alongside the content", () => {
    render(<Harness />);
    typeText("helloworld");
    caretAtTextOffset(5);
    advance(2000);
    act(() => api.pasteText("-X-"));
    expect(input().textContent).toBe("hello-X-world");
    expect(flatCaret()).toBe(8);

    undo();
    expect(input().textContent).toBe("helloworld");
    expect(flatCaret()).toBe(5);

    redo();
    expect(input().textContent).toBe("hello-X-world");
    expect(flatCaret()).toBe(8);
  });

  it("starts a new undo unit when typing replaces a selection", () => {
    render(<Harness />);
    typeText("hello");
    // Select-all within the coalescing window, then type over it
    act(() => {
      const sel = window.getSelection()!;
      const r = document.createRange();
      r.selectNodeContents(input());
      sel.removeAllRanges();
      sel.addRange(r);
    });
    act(() => {
      fireBeforeInput("insertText");
      input().textContent = "x";
      caretToEnd();
      input().dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(input().textContent).toBe("x");

    undo();
    expect(input().textContent).toBe("hello");
    undo();
    expect(input().textContent).toBe("");
  });

  it("does not resurrect the transient tile highlight on undo", () => {
    render(<Harness pasteTilesEnabled />);
    const longText = "line1\nline2\nline3\nline4\nline5";
    act(() => api.pasteText(longText));
    expect(input().querySelector("[data-rich-tile]")).not.toBeNull();

    function pressBackspace(): void {
      act(() => {
        const event = new KeyboardEvent("keydown", {
          key: "Backspace",
          bubbles: true,
          cancelable: true,
        });
        api.handleTileKeyDown(
          event as unknown as React.KeyboardEvent<HTMLDivElement>
        );
      });
    }

    pressBackspace(); // first press selects the tile
    expect(input().querySelector(".rich-input-tile-selected")).not.toBeNull();
    pressBackspace(); // second press deletes it
    expect(input().querySelector("[data-rich-tile]")).toBeNull();

    undo();
    const tile = input().querySelector("[data-rich-tile]");
    expect(tile).not.toBeNull();
    expect(tile!.classList.contains("rich-input-tile-selected")).toBe(false);
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

describe("pushBoundedSnapshot", () => {
  function snap(chars: number): EditableSnapshot {
    return { html: "x".repeat(chars), selStart: 0, selEnd: 0 };
  }

  it("keeps retained history within the size cap", () => {
    const stack: EditableSnapshot[] = [];
    const size = Math.ceil(MAX_UNDO_TOTAL_CHARS * 0.45);
    pushBoundedSnapshot(stack, snap(size));
    pushBoundedSnapshot(stack, snap(size));
    pushBoundedSnapshot(stack, snap(size));
    expect(stack.length).toBe(2);
    const total = stack.reduce((sum, s) => sum + s.html.length, 0);
    expect(total).toBeLessThanOrEqual(MAX_UNDO_TOTAL_CHARS);
  });

  it("always retains the newest snapshot, even oversized", () => {
    const stack: EditableSnapshot[] = [];
    pushBoundedSnapshot(stack, snap(MAX_UNDO_TOTAL_CHARS + 1));
    pushBoundedSnapshot(stack, snap(MAX_UNDO_TOTAL_CHARS + 1));
    expect(stack.length).toBe(1);
  });

  it("enforces the entry-count cap", () => {
    const stack: EditableSnapshot[] = [];
    for (let i = 0; i < MAX_UNDO_ENTRIES + 5; i++) {
      pushBoundedSnapshot(stack, snap(1));
    }
    expect(stack.length).toBe(MAX_UNDO_ENTRIES);
  });
});
