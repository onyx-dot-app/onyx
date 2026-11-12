"use client";
import {
  useState,
  useEffect,
  useRef,
  type ReactNode,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { cn } from "@opal/utils";
import { useDirection } from "@radix-ui/react-direction";

interface PreviewSidebarProps {
  label: string;
  children: ReactNode | ((width: number) => ReactNode);
  initialWidth?: number;
  hidden?: boolean;
}

export default function PreviewSidebar({
  label,
  children,
  initialWidth = 144,
  hidden = false,
}: PreviewSidebarProps) {
  const direction = useDirection();
  const sidebarRef = useRef<HTMLDivElement>(null);
  const resizeGesture = useRef<{
    pointerId: number;
    startX: number;
    width: number;
  } | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(initialWidth);
  const [layoutWidth, setLayoutWidth] = useState(0);
  const minimumWidth = 88;
  const maximumWidth = layoutWidth
    ? Math.max(minimumWidth, Math.min(320, layoutWidth * 0.4))
    : 320;
  const width = Math.max(minimumWidth, Math.min(maximumWidth, sidebarWidth));
  useEffect(() => {
    const layout = sidebarRef.current?.parentElement;
    if (!layout) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setLayoutWidth(entry.contentRect.width);
    });
    observer.observe(layout);
    return () => observer.disconnect();
  }, []);

  function resizeAt(clientX: number) {
    const gesture = resizeGesture.current;
    if (!gesture) return;
    const delta = (clientX - gesture.startX) * (direction === "rtl" ? -1 : 1);
    setSidebarWidth(
      Math.max(minimumWidth, Math.min(maximumWidth, gesture.width + delta))
    );
  }

  function finishResize(
    event: PointerEvent<HTMLDivElement>,
    cancelled = false
  ) {
    if (resizeGesture.current?.pointerId !== event.pointerId) return;
    if (!cancelled) resizeAt(event.clientX);
    resizeGesture.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function resizeWithKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    const step = direction === "rtl" ? -10 : 10;
    const next =
      event.key === "Home"
        ? minimumWidth
        : event.key === "End"
          ? maximumWidth
          : event.key === "ArrowRight"
            ? width + step
            : event.key === "ArrowLeft"
              ? width - step
              : null;
    if (next === null) return;
    event.preventDefault();
    event.stopPropagation();
    setSidebarWidth(Math.max(minimumWidth, Math.min(maximumWidth, next)));
  }

  return (
    <>
      <div
        hidden={hidden}
        ref={sidebarRef}
        style={{ width }}
        className="min-h-0 shrink-0 overflow-hidden"
      >
        {typeof children === "function" ? children(width) : children}
      </div>
      <div
        role="separator"
        hidden={hidden}
        tabIndex={hidden ? -1 : 0}
        aria-label={label}
        aria-orientation="vertical"
        aria-valuemin={minimumWidth}
        aria-valuemax={Math.round(maximumWidth)}
        aria-valuenow={Math.round(width)}
        className={cn(
          "group w-2 shrink-0 justify-center cursor-col-resize touch-none focus-visible:outline focus-visible:outline-1 focus-visible:outline-border-03",
          hidden ? "hidden" : "flex"
        )}
        onPointerDown={(event) => {
          if (event.button !== 0 || resizeGesture.current) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          resizeGesture.current = {
            pointerId: event.pointerId,
            startX: event.clientX,
            width,
          };
        }}
        onPointerMove={(event) => {
          if (resizeGesture.current?.pointerId === event.pointerId)
            resizeAt(event.clientX);
        }}
        onPointerUp={(event) => finishResize(event)}
        onPointerCancel={(event) => finishResize(event, true)}
        onLostPointerCapture={() => {
          resizeGesture.current = null;
        }}
        onKeyDown={resizeWithKeyboard}
      >
        <div className="pointer-events-none w-1 border-e border-border-02 group-hover:bg-border-01 group-focus-visible:bg-border-01" />
      </div>
    </>
  );
}
