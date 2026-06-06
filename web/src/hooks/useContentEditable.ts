import { useCallback, useEffect, useRef, useState } from "react";
import {
  setCursorToEnd as setCursorToEndUtil,
  setCursorAfterNode,
  setCursorBeforeNode,
  insertTextAtCursor as insertTextAtCursorUtil,
  insertNodeAtCursor as insertNodeAtCursorUtil,
  getTextContent,
  deleteTokenBeforeCursor,
  stripLeadingBr,
} from "@/lib/contentEditable";
import {
  createRichInputTileNode,
  getAdjacentRichTile,
  shouldCreatePasteTile,
  getPasteTilePreview,
  getPasteTileMeta,
  isSkillTile,
  SKILL_TILE_TYPE,
} from "@/lib/richInputTile";

type PasteTileData = { text: string; tile: HTMLElement };

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
  insertTileAtCursor: (text: string) => HTMLElement | null;
  expandTile: (tile: HTMLElement) => void;
  /** Insert a skill tile, replacing `beforeToken` (the `/<query>` before the caret). */
  insertSkillTile: (slug: string, name: string, beforeToken: string) => boolean;
  pasteText: (text: string) => void;
  /** Whether to show the "paste again to expand" hint — true while a paste tile exists. */
  pasteExpandHintVisible: boolean;
  handleCopy: (event: React.ClipboardEvent<HTMLDivElement>) => void;
  handleCut: (event: React.ClipboardEvent<HTMLDivElement>) => void;
  setCursorToEnd: () => void;
  resize: () => void;
  handleTileMouseDown: (event: React.MouseEvent<HTMLDivElement>) => void;
  handleTileClick: (event: React.MouseEvent<HTMLDivElement>) => void;
  handleTileKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => boolean;
  tilePopover: PasteTileData | null;
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
  const plainPasteRef = useRef(false);
  const [tilePopover, setTilePopover] = useState<PasteTileData | null>(null);
  const [pasteExpandHintVisible, setPasteExpandHintVisible] = useState(false);

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
    setPasteExpandHintVisible(
      !!el.querySelector('[data-rich-tile][data-tile-type="paste"]')
    );
    onContentChangeRef.current?.(text);
    return text;
  }, []);

  const handleInput = useCallback(
    (_event: React.SyntheticEvent<HTMLDivElement>): string => {
      if (isComposingRef.current) return messageRef.current;
      clearTileSelection();
      const el = ref.current;
      if (el && stripLeadingBr(el)) {
        // The stray <br> sat before the caret-at-start; collapse to the start.
        const s = window.getSelection();
        if (s) {
          const r = document.createRange();
          r.setStart(el, 0);
          r.collapse(true);
          s.removeAllRanges();
          s.addRange(r);
        }
      }
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
    plainPasteRef.current = false;
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
      setPasteExpandHintVisible(false);

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
    setPasteExpandHintVisible(false);

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
    (text: string): HTMLElement | null => {
      if (!ref.current) return null;
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
      return tile;
    },
    [syncFromDOM, resize]
  );

  const expandTile = useCallback(
    (tile: HTMLElement) => {
      const el = ref.current;
      if (!el || !el.contains(tile)) return;

      const sel = window.getSelection();
      const caret =
        sel && sel.rangeCount > 0 ? sel.getRangeAt(0).cloneRange() : null;

      const textNode = document.createTextNode(
        tile.getAttribute("data-text") ?? ""
      );
      tile.replaceWith(textNode);

      if (selectedTileRef.current === tile) selectedTileRef.current = null;
      setTilePopover(null);

      el.focus();
      // Restore the caret if it's still in the input; a caret on the now-detached
      // tile (or in the popover) fails this and falls back to the text end.
      if (
        caret &&
        el.contains(caret.startContainer) &&
        el.contains(caret.endContainer)
      ) {
        sel!.removeAllRanges();
        sel!.addRange(caret);
      } else {
        setCursorAfterNode(textNode);
        el.normalize();
      }

      syncFromDOM();
      resize();
    },
    [syncFromDOM, resize]
  );

  const insertSkillTile = useCallback(
    (slug: string, name: string, beforeToken: string): boolean => {
      const el = ref.current;
      if (!el) return false;
      // Replacing a typed `/<query>`: bail if it can't be verifiably removed,
      // since the tile serializes back to `/<slug> ` and would duplicate it. An
      // empty `beforeToken` (e.g. paste) just inserts at the caret.
      if (beforeToken && !deleteTokenBeforeCursor(el, beforeToken))
        return false;
      const tile = createRichInputTileNode({
        type: SKILL_TILE_TYPE,
        text: `/${slug} `,
        preview: `Skill: ${name}`,
        meta: "",
        skillSlug: slug,
      });
      insertNodeAtCursorUtil(el, tile); // also places the caret after the tile
      syncFromDOM();
      resize();
      return true;
    },
    [syncFromDOM, resize]
  );

  const findMatchingPasteTile = useCallback(
    (text: string): HTMLElement | null => {
      const el = ref.current;
      if (!el) return null;
      const tiles = Array.from(
        el.querySelectorAll<HTMLElement>("[data-rich-tile]")
      );
      return (
        tiles.find(
          (tile) =>
            !isSkillTile(tile) && tile.getAttribute("data-text") === text
        ) ?? null
      );
    },
    []
  );

  const pasteText = useCallback(
    (text: string) => {
      const plainPaste = plainPasteRef.current;
      plainPasteRef.current = false;

      if (pasteTilesEnabled && !plainPaste && shouldCreatePasteTile(text)) {
        const existing = findMatchingPasteTile(text);
        if (existing) {
          expandTile(existing);
          return;
        }
        insertTileAtCursor(text);
      } else {
        insertTextAtCursor(text);
      }
    },
    [
      pasteTilesEnabled,
      insertTileAtCursor,
      insertTextAtCursor,
      expandTile,
      findMatchingPasteTile,
    ]
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
        // Skill tiles don't use the paste-edit popover; their click handling
        // (re-pick) lives in the host input bar.
        if (isSkillTile(tile)) return;
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
      const isModifier =
        event.key === "Control" ||
        event.key === "Meta" ||
        event.key === "Shift" ||
        event.key === "Alt";
      const isPasteShortcut =
        (event.ctrlKey || event.metaKey) &&
        (event.key === "v" || event.key === "V");
      // Arm plain paste on Ctrl/Cmd+Shift+V; any other key disarms a stale flag.
      if (isPasteShortcut) {
        plainPasteRef.current = event.shiftKey;
      } else if (!isModifier) {
        plainPasteRef.current = false;
      }

      const isNav = event.key === "ArrowLeft" || event.key === "ArrowRight";
      const isDelete = event.key === "Backspace" || event.key === "Delete";

      // Enter on selected tile → open popover (paste tiles only; skill tiles
      // have no editable text, so Enter is a no-op that keeps them selected).
      if (event.key === "Enter" && selectedTileRef.current) {
        event.preventDefault();
        const tile = selectedTileRef.current;
        if (isSkillTile(tile)) return true;
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
          // Deselect; let the native arrow collapse the selection to the right
          // edge (it renders the caret correctly, unlike a manual tile-boundary
          // range, which had no caret rect and needed a second press).
          clearTileSelection();
          return false;
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

      // Chrome deletes a leading contentEditable=false tile when Backspace is
      // pressed with nothing before the caret. That deletion is a no-op anyway
      // (nothing to the left), so block it — otherwise it eats the tile or
      // leaves an empty first line above it.
      const el = ref.current;
      if (
        event.key === "Backspace" &&
        el &&
        el.contains(range.startContainer)
      ) {
        const before = document.createRange();
        before.selectNodeContents(el);
        before.setEnd(range.startContainer, range.startOffset);
        // Collapsed ⇒ nothing precedes the caret.
        if (before.collapsed) {
          event.preventDefault();
          return true;
        }
      }

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
      selectedTileRef.current = null;
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
    expandTile,
    insertSkillTile,
    pasteText,
    pasteExpandHintVisible,
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
