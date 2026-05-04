import { useCallback, useEffect, useRef, useState } from "react";
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
  setCursorToEnd: () => void;
  resize: () => void;
}

export function useContentEditable({
  initialContent = "",
  wrapperRef,
  minHeight = 44,
  maxHeight = 200,
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

    // Clean up stale <br> that browsers leave in empty contentEditable divs.
    // Only when not composing and when the only content is non-text nodes (e.g. <br>).
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
      const text = syncFromDOM();
      resize();
      return text;
    },
    [syncFromDOM, resize]
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
    [resize]
  );

  const clearMessage = useCallback(() => {
    if (!ref.current) return;

    ref.current.innerHTML = "";
    messageRef.current = "";
    setMessageState("");
    resize();
    onContentChangeRef.current?.("");
  }, [resize]);

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
    setMessage,
    clearMessage,
    handleInput,
    handleCompositionStart,
    handleCompositionEnd,
    insertTextAtCursor,
    setCursorToEnd,
    resize,
  };
}
