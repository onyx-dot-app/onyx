import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  setCursorToEnd as setCursorToEndUtil,
  insertTextAtCursor as insertTextAtCursorUtil,
  getTextContent,
} from "@/lib/contentEditable";

export interface UseContentEditableOptions {
  initialContent?: string;
  wrapperRef: React.RefObject<HTMLDivElement | null>;
  minHeight?: number;
  maxHeight?: number;
  onContentChange?: (text: string) => void;
}

export interface UseContentEditableReturn {
  ref: React.RefObject<HTMLDivElement | null>;
  message: string;
  isEmpty: boolean;
  setContent: (text: string) => void;
  clearContent: () => void;
  handleInput: (event: React.FormEvent<HTMLDivElement>) => void;
  handleCompositionStart: () => void;
  handleCompositionEnd: () => void;
  insertTextAtCursor: (text: string) => void;
  setCursorToEnd: () => void;
  resize: () => void;
}

export function useContentEditable({
  initialContent = "",
  wrapperRef,
  minHeight = 44,
  maxHeight = 200,
  onContentChange,
}: UseContentEditableOptions): UseContentEditableReturn {
  const ref = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState(initialContent);
  const isEmpty = useMemo(() => !message, [message]);
  const isComposingRef = useRef(false);
  const onContentChangeRef = useRef(onContentChange);
  const rafRef = useRef<number | null>(null);
  const wrapperPaddingYRef = useRef(0);

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
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
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

  const updateEmpty = useCallback((el: HTMLElement, text: string) => {
    if (text) {
      el.removeAttribute("data-empty");
    } else {
      el.setAttribute("data-empty", "");
    }
  }, []);

  const syncFromDOM = useCallback(() => {
    const el = ref.current;
    if (!el) return;

    // Clean up stale <br> that browsers leave in empty contentEditable divs.
    // Only when not composing and when the only content is non-text nodes (e.g. <br>).
    if (!isComposingRef.current && !el.textContent && el.innerHTML) {
      el.innerHTML = "";
    }

    const text = getTextContent(el);
    setMessage(text);
    updateEmpty(el, text);
    onContentChangeRef.current?.(text);
  }, [updateEmpty]);

  const handleInput = useCallback(
    (_event: React.FormEvent<HTMLDivElement>) => {
      if (isComposingRef.current) return;
      syncFromDOM();
      resize();
    },
    [syncFromDOM, resize]
  );

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false;
    syncFromDOM();
    resize();
  }, [syncFromDOM, resize]);

  const setContent = useCallback(
    (text: string) => {
      if (!ref.current) return;

      ref.current.textContent = text;
      setMessage(text);
      updateEmpty(ref.current, text);
      resize();
      onContentChangeRef.current?.(text);

      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        if (ref.current) {
          setCursorToEndUtil(ref.current);
        }
      });
    },
    [resize, updateEmpty]
  );

  const clearContent = useCallback(() => {
    if (!ref.current) return;

    ref.current.innerHTML = "";
    setMessage("");
    updateEmpty(ref.current, "");
    resize();
    onContentChangeRef.current?.("");
  }, [resize, updateEmpty]);

  const insertTextAtCursor = useCallback(
    (text: string) => {
      if (!ref.current) return;
      insertTextAtCursorUtil(ref.current, text);
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
    isEmpty,
    setContent,
    clearContent,
    handleInput,
    handleCompositionStart,
    handleCompositionEnd,
    insertTextAtCursor,
    setCursorToEnd,
    resize,
  };
}
