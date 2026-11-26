/**
 * The chat browser's live view: the page's frames on a canvas, and the
 * user's mouse, wheel and keys sent to the page while they control it.
 *
 * Ported from T3 Code (apps/web/src/browser/ServerBrowserSurface.tsx).
 * Copyright (c) 2026 T3 Tools Inc. Licensed under the MIT License.
 */
"use client";

import {
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
  useEffect,
  useEffectEvent,
  useId,
  useRef,
} from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import {
  agentCursorPosition,
  browserModifiers,
  historyDeltaOf,
  type LastClick,
  mouseButtonOf,
  nextClick,
  pagePointFromClient,
  type PagePoint,
  pressedButtonOf,
  splitBrowserText,
  wheelDeltaUnit,
} from "@/lib/chat/browser/stream";
import type {
  BrowserMouseButton,
  BrowserPointer,
  BrowserViewerControl,
  BrowserViewerMessage,
  BrowserViewport,
} from "@/lib/chat/browser/types";
import { AgentBrowserCursor } from "@/sections/chat/browser/AgentBrowserCursor";

// Android keyboards report Backspace as text deletion, so keep a deletable
// sentinel in the key field
const INPUT_SENTINEL = "​";
const BACKSPACE = { key: "Backspace", code: "Backspace", keyCode: 8 } as const;
const DELETE = { key: "Delete", code: "Delete", keyCode: 46 } as const;
const COPY = { key: "c", code: "KeyC", keyCode: 67 } as const;
const CUT = { key: "x", code: "KeyX", keyCode: 88 } as const;
const CTRL = 2;
const TAP_SLOP_PX = 8;

type KeyPress = typeof BACKSPACE | typeof DELETE | typeof COPY | typeof CUT;
type MouseMessage = Extract<BrowserViewerMessage, { type: "mouse" }>;
type WheelMessage = Extract<BrowserViewerMessage, { type: "wheel" }>;
type KeyMessage = Extract<BrowserViewerMessage, { type: "key" }>;

interface TouchGesture {
  pointerId: number;
  startX: number;
  startY: number;
  lastX: number;
  lastY: number;
  panning: boolean;
}

interface BrowserSurfaceProps {
  canvasRef: RefObject<HTMLCanvasElement | null>;
  control: BrowserViewerControl | null;
  viewport: BrowserViewport | null;
  hasFrame: boolean;
  agentPointer: BrowserPointer | null;
  send: (message: BrowserViewerMessage) => boolean;
}

export function BrowserSurface({
  canvasRef,
  control,
  viewport,
  hasFrame,
  agentPointer,
  send,
}: BrowserSurfaceProps) {
  const t = useTranslations("chat.browser");
  const controlling = control === "you";
  const descriptionId = useId();
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const keySentRef = useRef(false);
  // Keys down on the page, by code, to let go of when focus leaves it
  const heldKeysRef = useRef(new Map<string, KeyMessage>());
  const pendingMoveRef = useRef<MouseMessage | null>(null);
  const pendingWheelRef = useRef<WheelMessage | null>(null);
  const inputFrameRef = useRef<number | null>(null);
  const mouseButtonsRef = useRef(0);
  const mouseClicksRef = useRef<Record<BrowserMouseButton, number>>({
    left: 1,
    middle: 1,
    right: 1,
    none: 1,
  });
  const lastClickRef = useRef<LastClick | null>(null);
  const touchRef = useRef<TouchGesture | null>(null);

  const flushInput = () => {
    if (inputFrameRef.current !== null)
      cancelAnimationFrame(inputFrameRef.current);
    inputFrameRef.current = null;
    const move = pendingMoveRef.current;
    const wheel = pendingWheelRef.current;
    pendingMoveRef.current = null;
    pendingWheelRef.current = null;
    if (move) send(move);
    if (wheel) send(wheel);
  };

  const scheduleFlush = () => {
    if (inputFrameRef.current === null)
      inputFrameRef.current = requestAnimationFrame(flushInput);
  };

  const queueWheel = (
    point: PagePoint,
    deltaX: number,
    deltaY: number,
    modifiers: number
  ) => {
    const pending = pendingWheelRef.current;
    pendingWheelRef.current = {
      type: "wheel",
      x: point.x,
      y: point.y,
      deltaX: (pending?.deltaX ?? 0) + deltaX,
      deltaY: (pending?.deltaY ?? 0) + deltaY,
      modifiers,
    };
    scheduleFlush();
  };

  const pagePoint = (
    clientX: number,
    clientY: number,
    clamp: boolean
  ): PagePoint | null => {
    const canvas = canvasRef.current;
    if (!canvas || !viewport || !hasFrame || !controlling) return null;
    const rect = canvas.getBoundingClientRect();
    return pagePointFromClient(
      clientX,
      clientY,
      rect,
      { width: canvas.width, height: canvas.height },
      viewport,
      clamp
    );
  };

  const countClick = (
    button: BrowserMouseButton,
    x: number,
    y: number,
    time: number
  ): number => {
    const click = nextClick(lastClickRef.current, button, time, x, y);
    lastClickRef.current = click;
    return click.count;
  };

  // Losing control drops the input in flight and the key field's focus
  useEffect(() => {
    if (controlling) return;
    if (inputFrameRef.current !== null)
      cancelAnimationFrame(inputFrameRef.current);
    inputFrameRef.current = null;
    pendingMoveRef.current = pendingWheelRef.current = null;
    mouseButtonsRef.current = 0;
    lastClickRef.current = null;
    touchRef.current = null;
    keySentRef.current = false;
    heldKeysRef.current.clear();
    inputRef.current?.blur();
  }, [controlling]);

  useEffect(
    () => () => {
      if (inputFrameRef.current !== null)
        cancelAnimationFrame(inputFrameRef.current);
    },
    []
  );

  // Native, as React's wheel listener is passive and cannot stop the panel
  // from scrolling
  const onWheel = useEffectEvent((event: WheelEvent) => {
    const point = pagePoint(event.clientX, event.clientY, false);
    if (!point) return;
    event.preventDefault();
    const unit = wheelDeltaUnit(event.deltaMode, viewport?.height ?? 0);
    queueWheel(
      point,
      event.deltaX * unit,
      event.deltaY * unit,
      browserModifiers(event)
    );
  });
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const listener = (event: WheelEvent) => onWheel(event);
    canvas.addEventListener("wheel", listener, { passive: false });
    return () => canvas.removeEventListener("wheel", listener);
  }, [canvasRef]);

  const handlePointer = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!controlling) return;
    // Thumb buttons move the tab's history in handleMouseUp
    if (historyDeltaOf(event.button) !== null) return;
    const { type, pointerId, clientX, clientY } = event;
    const cancelled = type === "pointercancel";
    const touch = touchRef.current;
    if (cancelled && touch?.pointerId === pointerId) {
      touchRef.current = null;
      return;
    }
    if (event.pointerType === "touch" && !cancelled) {
      const point = pagePoint(clientX, clientY, type === "pointermove");
      if (type === "pointerdown") {
        if (!event.isPrimary) return;
        touchRef.current = {
          pointerId,
          startX: clientX,
          startY: clientY,
          lastX: clientX,
          lastY: clientY,
          panning: false,
        };
        return;
      }
      if (!touch || touch.pointerId !== pointerId) return;
      if (type === "pointermove") {
        if (
          !touch.panning &&
          Math.hypot(clientX - touch.startX, clientY - touch.startY) <
            TAP_SLOP_PX
        )
          return;
        touch.panning = true;
        if (point)
          queueWheel(
            point,
            (touch.lastX - clientX) * point.scale,
            (touch.lastY - clientY) * point.scale,
            0
          );
        touch.lastX = clientX;
        touch.lastY = clientY;
        return;
      }
      touchRef.current = null;
      if (touch.panning || !point) return;
      inputRef.current?.focus({ preventScroll: true });
      flushInput();
      const clickCount = countClick("left", clientX, clientY, event.timeStamp);
      const at = { x: point.x, y: point.y, modifiers: 0 };
      send({
        type: "mouse",
        action: "move",
        ...at,
        button: "none",
        buttons: 0,
        clickCount: 0,
      });
      send({
        type: "mouse",
        action: "down",
        ...at,
        button: "left",
        buttons: 1,
        clickCount,
      });
      send({
        type: "mouse",
        action: "up",
        ...at,
        button: "left",
        buttons: 0,
        clickCount,
      });
      return;
    }
    const previous = mouseButtonsRef.current;
    if ((cancelled || type === "pointerup") && previous === 0) return;
    if (cancelled || type === "pointerup")
      mouseButtonsRef.current = cancelled ? 0 : event.buttons & 7;
    const point = pagePoint(
      clientX,
      clientY,
      type !== "pointerdown" &&
        (cancelled ||
          type === "pointerup" ||
          previous !== 0 ||
          event.buttons !== 0)
    );
    if (!point) return;
    const at = {
      x: point.x,
      y: point.y,
      modifiers: browserModifiers(event),
    };
    const mouse = (
      action: "down" | "up",
      button: BrowserMouseButton,
      buttons: number
    ) => {
      if (action === "down")
        mouseClicksRef.current[button] = countClick(
          button,
          clientX,
          clientY,
          event.timeStamp
        );
      send({
        type: "mouse",
        action,
        ...at,
        button,
        buttons,
        clickCount: mouseClicksRef.current[button],
      });
    };
    if (type === "pointerdown") {
      inputRef.current?.focus({ preventScroll: true });
      event.currentTarget.setPointerCapture(pointerId);
      flushInput();
      mouseButtonsRef.current = event.buttons & 7;
      mouse("down", mouseButtonOf(event.button), event.buttons);
    } else if (type === "pointerup") {
      flushInput();
      mouse("up", mouseButtonOf(event.button), event.buttons);
    } else {
      // Chords arrive as pointermove; a cancel releases every held button
      const next = cancelled ? 0 : event.buttons & 7;
      const changed = previous ^ next;
      if (previous !== 0 && changed !== 0) {
        flushInput();
        let buttons = previous;
        for (const bit of [1, 2, 4]) {
          if (!(changed & bit)) continue;
          buttons ^= bit;
          mouse(next & bit ? "down" : "up", pressedButtonOf(bit), buttons);
        }
        mouseButtonsRef.current = next;
      }
      if (cancelled) return;
      pendingMoveRef.current = {
        type: "mouse",
        action: "move",
        ...at,
        button: pressedButtonOf(event.buttons),
        buttons: event.buttons,
        clickCount: 0,
      };
      scheduleFlush();
    }
  };

  // Chromium runs a thumb button's back or forward on mouseup here, which
  // would move the app. Send it to the tab instead.
  const onMouseUp = useEffectEvent((event: MouseEvent) => {
    const delta = historyDeltaOf(event.button);
    if (delta === null) return;
    event.preventDefault();
    if (controlling) send({ type: "history", delta });
  });
  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;
    const listener = (event: MouseEvent) => onMouseUp(event);
    surface.addEventListener("mouseup", listener);
    return () => surface.removeEventListener("mouseup", listener);
  }, []);

  const resetInput = (textarea: HTMLTextAreaElement) => {
    keySentRef.current = false;
    textarea.value = INPUT_SENTINEL;
    textarea.setSelectionRange(INPUT_SENTINEL.length, INPUT_SENTINEL.length);
  };

  const sendText = (text: string) => {
    for (const chunk of splitBrowserText(text))
      send({ type: "text", text: chunk });
  };

  const sendKeyPress = (key: KeyPress, modifiers = 0) => {
    send({ type: "key", action: "down", ...key, modifiers });
    send({ type: "key", action: "up", ...key, modifiers });
  };

  // The Edit menu's Copy and Cut fire no key, so send the shortcut
  const handleClipboard = (key: KeyPress, event: ClipboardEvent) => {
    // Keeps the sentinel off the clipboard
    event.preventDefault();
    if (controlling) sendKeyPress(key, CTRL);
  };

  const handleKey = (
    action: "down" | "up",
    event: KeyboardEvent<HTMLTextAreaElement>
  ) => {
    if (!controlling) return;
    keySentRef.current = false;
    if (
      event.nativeEvent.isComposing ||
      event.keyCode === 229 ||
      event.key === "Process" ||
      event.key === "Unidentified"
    )
      return;
    // Shift+Escape leaves the page; Escape alone goes to it
    if (event.key === "Escape" && event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      if (action === "down") event.currentTarget.blur();
      return;
    }
    const shortcut = event.ctrlKey || event.metaKey;
    // Paste arrives as text through onPaste
    if (shortcut && event.key.toLowerCase() === "v") return;
    if (event.shiftKey && event.key === "Insert") return;
    // Enter carries "\r", so forms submit and text areas break lines
    const text = shortcut
      ? undefined
      : [...event.key].length === 1
        ? event.key
        : event.key === "Enter"
          ? "\r"
          : undefined;
    const key: KeyMessage = {
      type: "key",
      action,
      key: event.key,
      code: event.code,
      keyCode: event.keyCode,
      modifiers: browserModifiers(event),
    };
    if (action === "down" && text !== undefined) key.text = text;
    send(key);
    if (action === "down")
      heldKeysRef.current.set(event.code || event.key, key);
    else heldKeysRef.current.delete(event.code || event.key);
    // Some Android keyboards edit the field even when keydown is prevented
    keySentRef.current =
      action === "down" &&
      !shortcut &&
      (text !== undefined ||
        event.key === "Backspace" ||
        event.key === "Delete");
    // The page copies or cuts; stop the browser's own copy or cut
    if (
      event.ctrlKey !== event.metaKey &&
      !event.altKey &&
      !event.shiftKey &&
      ["c", "x"].includes(event.key.toLowerCase())
    )
      event.preventDefault();
    if (shortcut) return;
    event.preventDefault();
    event.stopPropagation();
  };

  // Keys up after focus left go to the app, so the page would keep them
  // down. A lost control already let go of them.
  const releaseKeys = () => {
    if (controlling)
      for (const key of heldKeysRef.current.values())
        send({
          type: "key",
          action: "up",
          key: key.key,
          code: key.code,
          keyCode: key.keyCode,
          modifiers: 0,
        });
    heldKeysRef.current.clear();
  };

  const handleInput = (event: FormEvent<HTMLTextAreaElement>) => {
    const native = event.nativeEvent;
    if (native instanceof InputEvent && native.isComposing) return;
    const textarea = event.currentTarget;
    const inputType = native instanceof InputEvent ? native.inputType : "";
    if (keySentRef.current) keySentRef.current = false;
    else if (inputType === "deleteContentBackward") sendKeyPress(BACKSPACE);
    else if (inputType === "deleteContentForward") sendKeyPress(DELETE);
    else {
      const text = textarea.value.replace(/^​/, "");
      if (text) sendText(text);
    }
    resetInput(textarea);
  };

  const canvas = canvasRef.current;
  const cursor =
    agentPointer && !controlling && canvas && viewport
      ? agentCursorPosition(
          agentPointer,
          { width: canvas.clientWidth, height: canvas.clientHeight },
          { width: canvas.width, height: canvas.height },
          viewport
        )
      : null;

  return (
    <div
      ref={surfaceRef}
      className="absolute inset-0 overflow-hidden"
      data-chat-browser-surface
    >
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className={cn(
          "block size-full touch-none object-contain",
          !hasFrame && "invisible"
        )}
        onPointerDown={handlePointer}
        onPointerMove={handlePointer}
        onPointerUp={handlePointer}
        onPointerCancel={handlePointer}
        onMouseDown={(event) => event.preventDefault()}
        onContextMenu={(event) => event.preventDefault()}
      />
      {cursor && agentPointer && (
        <AgentBrowserCursor
          phase={agentPointer.phase}
          sequence={agentPointer.sequence}
          left={cursor.left}
          top={cursor.top}
        />
      )}
      <span id={descriptionId} className="sr-only">
        <Text>{t("surface.inputDescription")}</Text>
      </span>
      {/* Takes the keys and text for the page. Pinned to the top corner so
          focus does not scroll; 16px stops iOS from zooming on focus. */}
      {/* oxlint-disable-next-line react/forbid-elements -- hidden key capture for the remote page, not a form field */}
      <textarea
        ref={inputRef}
        aria-label={t("surface.inputLabel")}
        aria-describedby={descriptionId}
        autoCapitalize="off"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        disabled={!controlling}
        defaultValue={INPUT_SENTINEL}
        onFocus={(event) => resetInput(event.currentTarget)}
        onBlur={releaseKeys}
        className="sr-only top-0 start-0 text-base"
        onKeyDown={(event) => handleKey("down", event)}
        onKeyUp={(event) => handleKey("up", event)}
        onInput={handleInput}
        onCompositionEnd={(event) => {
          const text = event.data.replace(/^​/, "");
          if (text) sendText(text);
          resetInput(event.currentTarget);
        }}
        onCopy={(event) => handleClipboard(COPY, event)}
        onCut={(event) => handleClipboard(CUT, event)}
        onPaste={(event) => {
          event.preventDefault();
          const text = event.clipboardData.getData("text/plain");
          if (text) sendText(text);
        }}
      />
    </div>
  );
}
