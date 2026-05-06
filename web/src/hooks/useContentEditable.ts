import { useCallback, useEffect, useRef, useState } from "react";
import {
  setCursorToEnd as setCursorToEndUtil,
  setCursorAfterNode,
  setCursorBeforeNode,
  insertTextAtCursor as insertTextAtCursorUtil,
  insertNodeAtCursor as insertNodeAtCursorUtil,
  getTextContent,
} from "@/lib/contentEditable";
import {
  createRichInputTileNode,
  getAdjacentRichTile,
  shouldCreatePasteTile,
  getPasteTilePreview,
  getPasteTileMeta,
} from "@/lib/richInputTile";

export interface UseContentEditableOptions {
  initialContent?: string;
  wrapperRef: React.RefObject<HTMLDivElement | null>;
  minHeight?: number;
  maxHeight?: number;
  pasteTilesEnabled?: boolean;
  onContentChange?: (text: string) => void;
  disabled?: boolean;
}

export interface UseContentEditableReturn {
  ref: React.RefObject<HTMLDivElement | null>;
  message: string;
  setMessage: (text: string) => void;
  clearMessage: () => void;
  handleInput: (event: React.SyntheticEvent<HTMLDivElement>) => string;
  handleCompositionStart: () => void;
  handleCompositionEnd: () => void;
  insertTextAtCursor: (text: string) => void;
  insertTileAtCursor: (text: string) => void;
  pasteText: (text: string) => void;
  handleCopy: (event: React.ClipboardEvent<HTMLDivElement>) => void;
  handleCut: (event: React.ClipboardEvent<HTMLDivElement>) => void;
  setCursorToEnd: () => void;
  resize: () => void;
  handleTileMouseDown: (event: React.MouseEvent<HTMLDivElement>) => void;
  handleTileClick: (event: React.MouseEvent<HTMLDivElement>) => void;
  handleTileKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => boolean;
  tilePopover: { text: string; tile: HTMLElement } | null;
  dismissTilePopover: () => void;
  updateTileText: (newText: string) => void;
}

export function useContentEditable({
  initialContent = "",
  wrapperRef,
  minHeight = 44,
  maxHeight = 200,
  pasteTilesEnabled = false,
  onContentChange,
  disabled = false,
}: UseContentEditableOptions): UseContentEditableReturn {
  const ref = useRef<HTMLDivElement>(null);
  const [message, setMessageState] = useState(initialContent);
  const messageRef = useRef(initialContent);
  const isComposingRef = useRef(false);
  const onContentChangeRef = useRef(onContentChange);
  const rafRef = useRef<number | null>(null);
  const wrapperPaddingYRef = useRef(0);
  const selectedTileRef = useRef<HTMLElement | null>(null);
  const [tilePopover, setTilePopover] = useState<{
    text: string;
    tile: HTMLElement;
  } | null>(null);

  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  }, [onContentChange]);

  useEffect(() => {
    if (wrapperRef.current) {
      const cs = getComputedStyle(wrapperRef.current);
      wrapperPaddingYRef.current =
        parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    }
  }, [wrapperRef]);

  useEffect(() => {
    if (disabled) return;
    ref.current?.focus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, []);

  // Track text selection to highlight tiles within the selection range.
  useEffect(() => {
    if (!pasteTilesEnabled) return;

    function handleSelectionChange() {
      const el = ref.current;
      if (!el || !el.contains(document.activeElement ?? null)) return;

      const sel = window.getSelection();
      const tiles = el.querySelectorAll("[data-rich-tile]");
      tiles.forEach((tile) => {
        const htmlTile = tile as HTMLElement;
        if (
          sel &&
          sel.rangeCount > 0 &&
          !sel.isCollapsed &&
          sel.getRangeAt(0).intersectsNode(tile)
        ) {
          htmlTile.classList.add("rich-input-tile-in-selection");
        } else {
          htmlTile.classList.remove("rich-input-tile-in-selection");
        }
      });
    }

    document.addEventListener("selectionchange", handleSelectionChange);
    return () =>
      document.removeEventListener("selectionchange", handleSelectionChange);
  }, [pasteTilesEnabled]);

  const clearTileSelection = useCallback(() => {
    if (selectedTileRef.current) {
      selectedTileRef.current.classList.remove("rich-input-tile-selected");
      selectedTileRef.current = null;
    }
  }, []);

  const resize = useCallback(() => {
    const wrapper = wrapperRef.current;
    const div = ref.current;
    if (!wrapper || !div) return;

    wrapper.style.height = `${minHeight}px`;
    const clamped = Math.min(
      Math.max(div.scrollHeight + wrapperPaddingYRef.current, minHeight),
      maxHeight
    );
    wrapper.style.height = `${clamped}px`;
  }, [wrapperRef, minHeight, maxHeight]);

  const syncFromDOM = useCallback((): string => {
    const el = ref.current;
    if (!el) return "";

    if (!isComposingRef.current && !el.textContent && el.innerHTML) {
      el.innerHTML = "";
    }

    const text = getTextContent(el);
    messageRef.current = text;
    setMessageState(text);
    onContentChangeRef.current?.(text);
    return text;
  }, []);

  const handleInput = useCallback(
    (_event: React.SyntheticEvent<HTMLDivElement>): string => {
      if (isComposingRef.current) return messageRef.current;
      clearTileSelection();
      const text = syncFromDOM();
      resize();
      return text;
    },
    [syncFromDOM, resize, clearTileSelection]
  );

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true;
    if (ref.current) {
      ref.current.removeAttribute("data-empty");
    }
  }, []);

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false;
    syncFromDOM();
    resize();
  }, [syncFromDOM, resize]);

  const disabledRef = useRef(disabled);
  useEffect(() => {
    disabledRef.current = disabled;
  }, [disabled]);

  const setMessage = useCallback(
    (text: string) => {
      if (!ref.current) return;

      clearTileSelection();
      setTilePopover(null);

      ref.current.textContent = text;
      messageRef.current = text;
      setMessageState(text);
      resize();
      onContentChangeRef.current?.(text);

      if (disabledRef.current) return;

      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        if (ref.current) {
          ref.current.focus();
          setCursorToEndUtil(ref.current);
        }
      });
    },
    [resize, clearTileSelection]
  );

  const clearMessage = useCallback(() => {
    if (!ref.current) return;

    clearTileSelection();
    setTilePopover(null);

    ref.current.innerHTML = "";
    messageRef.current = "";
    setMessageState("");
    resize();
    onContentChangeRef.current?.("");
  }, [resize, clearTileSelection]);

  const insertTextAtCursor = useCallback(
    (text: string) => {
      if (!ref.current) return;
      insertTextAtCursorUtil(ref.current, text);
      syncFromDOM();
      resize();
    },
    [syncFromDOM, resize]
  );

  const insertTileAtCursor = useCallback(
    (text: string) => {
      if (!ref.current) return;
      const tile = createRichInputTileNode({
        type: "paste",
        text,
        preview: getPasteTilePreview(text),
        meta: getPasteTileMeta(text),
      });
      insertNodeAtCursorUtil(ref.current, tile);
      setCursorAfterNode(tile);

      syncFromDOM();
      resize();
    },
    [syncFromDOM, resize]
  );

  const pasteText = useCallback(
    (text: string) => {
      if (pasteTilesEnabled && shouldCreatePasteTile(text)) {
        insertTileAtCursor(text);
      } else {
        insertTextAtCursor(text);
      }
    },
    [pasteTilesEnabled, insertTileAtCursor, insertTextAtCursor]
  );

  const handleTileMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      clearTileSelection();
      if (disabledRef.current) return;

      const target = event.target as HTMLElement;
      const removeBtn = target.closest("[data-rich-tile-remove]");
      if (!removeBtn) return;

      event.preventDefault();
      const tile = removeBtn.closest("[data-rich-tile]");
      if (tile) {
        tile.remove();
        setTilePopover(null);
        syncFromDOM();
        resize();
      }
    },
    [syncFromDOM, resize, clearTileSelection]
  );

  const handleTileClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (disabledRef.current) return;

      const target = event.target as HTMLElement;
      if (target.closest("[data-rich-tile-remove]")) return;

      const tile = target.closest("[data-rich-tile]") as HTMLElement | null;
      if (tile) {
        const text = tile.getAttribute("data-text") ?? "";
        setTilePopover({ text, tile });
      } else {
        setTilePopover(null);
        clearTileSelection();
      }
    },
    [clearTileSelection]
  );

  const dismissTilePopover = useCallback(() => {
    setTilePopover(null);
    syncFromDOM();
    ref.current?.focus();
    if (
      selectedTileRef.current &&
      ref.current?.contains(selectedTileRef.current)
    ) {
      const s = window.getSelection();
      if (s) {
        const r = document.createRange();
        r.selectNode(selectedTileRef.current);
        s.removeAllRanges();
        s.addRange(r);
      }
    }
  }, [syncFromDOM]);

  const updateTileText = useCallback(
    (newText: string) => {
      if (!tilePopover?.tile || !ref.current?.contains(tilePopover.tile))
        return;
      const { tile } = tilePopover;

      if (!newText.trim()) {
        const next = tile.nextSibling;
        const prev = tile.previousSibling;
        tile.remove();
        selectedTileRef.current = null;
        syncFromDOM();
        resize();
        setTilePopover(null);
        ref.current?.focus();
        if (next) {
          setCursorBeforeNode(next);
        } else if (prev) {
          setCursorAfterNode(prev);
        } else {
          setCursorToEndUtil(ref.current!);
        }
        ref.current?.normalize();
        return;
      }

      tile.setAttribute("data-text", newText);
      tile.title = newText.length > 200 ? newText.slice(0, 200) + "…" : newText;

      const preview = tile.querySelector(".rich-input-tile-preview");
      if (preview) {
        preview.textContent = getPasteTilePreview(newText);
      }
      const meta = tile.querySelector(".rich-input-tile-meta");
      if (meta) {
        meta.textContent = getPasteTileMeta(newText);
      }
    },
    [tilePopover, syncFromDOM, resize]
  );

  const handleTileKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>): boolean => {
      const isNav = event.key === "ArrowLeft" || event.key === "ArrowRight";
      const isDelete = event.key === "Backspace" || event.key === "Delete";

      // Enter on selected tile → open popover
      if (event.key === "Enter" && selectedTileRef.current) {
        event.preventDefault();
        const tile = selectedTileRef.current;
        const text = tile.getAttribute("data-text") ?? "";
        setTilePopover({ text, tile });
        return true;
      }

      // Modifier combos (Ctrl+C, Ctrl+X, etc.) pass through without deselecting
      if (event.ctrlKey || event.metaKey) {
        return false;
      }

      // Unrelated keys deselect tile and place cursor after it
      if (!isNav && !isDelete) {
        if (selectedTileRef.current) {
          const tile = selectedTileRef.current;
          clearTileSelection();
          setCursorAfterNode(tile);
        }
        setTilePopover(null);
        return false;
      }

      setTilePopover(null);

      // If a tile is already selected, handle second press
      if (selectedTileRef.current) {
        const selected = selectedTileRef.current;

        if (isNav) {
          // Arrow on selected tile → deselect and move cursor past it
          event.preventDefault();
          clearTileSelection();
          if (event.key === "ArrowRight") {
            setCursorAfterNode(selected);
          } else {
            const s = window.getSelection();
            if (s) {
              const r = document.createRange();
              r.setStartBefore(selected);
              r.collapse(true);
              s.removeAllRanges();
              s.addRange(r);
            }
          }
          return true;
        }

        if (isDelete) {
          event.preventDefault();
          selected.remove();
          selectedTileRef.current = null;
          syncFromDOM();
          resize();
          return true;
        }

        clearTileSelection();
        return false;
      }

      // No tile selected — check if cursor is adjacent to a tile
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) {
        return false;
      }

      const range = sel.getRangeAt(0);
      let direction: "before" | "after";
      if (isDelete) {
        direction = event.key === "Backspace" ? "before" : "after";
      } else {
        direction = event.key === "ArrowLeft" ? "before" : "after";
      }

      let tile = getAdjacentRichTile(range, direction);

      if (!tile) return false;

      // First press: highlight the tile and select it to hide the caret
      event.preventDefault();
      tile.classList.add("rich-input-tile-selected");
      selectedTileRef.current = tile;
      const s = window.getSelection();
      if (s) {
        const r = document.createRange();
        r.selectNode(tile);
        s.removeAllRanges();
        s.addRange(r);
      }
      return true;
    },
    [syncFromDOM, resize, clearTileSelection]
  );

  const handleCopy = useCallback(
    (event: React.ClipboardEvent<HTMLDivElement>) => {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;

      const range = sel.getRangeAt(0);
      if (!ref.current?.contains(range.commonAncestorContainer)) return;

      const fragment = range.cloneContents();
      const temp = document.createElement("div");
      temp.appendChild(fragment);

      if (!temp.querySelector("[data-rich-tile]")) return;

      event.preventDefault();
      event.clipboardData.setData("text/plain", getTextContent(temp));
    },
    []
  );

  const handleCut = useCallback(
    (event: React.ClipboardEvent<HTMLDivElement>) => {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;

      const range = sel.getRangeAt(0);
      if (!ref.current?.contains(range.commonAncestorContainer)) return;

      const fragment = range.cloneContents();
      const temp = document.createElement("div");
      temp.appendChild(fragment);

      if (!temp.querySelector("[data-rich-tile]")) return;

      event.preventDefault();
      event.clipboardData.setData("text/plain", getTextContent(temp));

      range.deleteContents();
      syncFromDOM();
      resize();
    },
    [syncFromDOM, resize]
  );

  const setCursorToEnd = useCallback(() => {
    if (!ref.current) return;
    setCursorToEndUtil(ref.current);
  }, []);

  return {
    ref,
    message,
    setMessage,
    clearMessage,
    handleInput,
    handleCompositionStart,
    handleCompositionEnd,
    insertTextAtCursor,
    insertTileAtCursor,
    pasteText,
    handleCopy,
    handleCut,
    setCursorToEnd,
    resize,
    handleTileMouseDown,
    handleTileClick,
    handleTileKeyDown,
    tilePopover,
    dismissTilePopover,
    updateTileText,
  };
}
