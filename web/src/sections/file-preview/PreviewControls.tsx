"use client";

import {
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { useDirection } from "@radix-ui/react-direction";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgChevronLeft, SvgChevronRight, SvgSidebar } from "@opal/icons";
import type { RichStr } from "@opal/types";

interface DocumentToolbarProps {
  label: string;
  thumbnailsLabel: string;
  previousLabel: string;
  nextLabel: string;
  // The page or slide counter between the arrows
  counter: string | RichStr;
  page: number;
  pageCount: number;
  showThumbnails: boolean;
  onToggleThumbnails: () => void;
  onPageChange: (page: number) => void;
  // Controls at the toolbar's end, such as zoom
  children?: ReactNode;
}

/**
 * The toolbar over a paged preview (PDF, slides), as Craft's: the thumbnail
 * toggle and the page arrows around a counter, then the host's controls.
 */
export function DocumentToolbar({
  label,
  thumbnailsLabel,
  previousLabel,
  nextLabel,
  counter,
  page,
  pageCount,
  showThumbnails,
  onToggleThumbnails,
  onPageChange,
  children,
}: DocumentToolbarProps) {
  // The chevrons mirror in a right-to-left page on their own
  return (
    <div
      role="toolbar"
      aria-label={label}
      className="shrink-0 border-b border-border-02 px-2 py-1.5"
    >
      <Section
        flexDirection="row"
        justifyContent="between"
        height="auto"
        gap={1}
        wrap
      >
        <Section flexDirection="row" width="fit" gap={1}>
          <Button
            icon={SvgSidebar}
            size="xs"
            prominence={showThumbnails ? "secondary" : "tertiary"}
            aria-label={thumbnailsLabel}
            aria-pressed={showThumbnails}
            onClick={onToggleThumbnails}
          />
          <Button
            icon={SvgChevronLeft}
            size="xs"
            prominence="tertiary"
            aria-label={previousLabel}
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          />
          <Text font="secondary-body" color="text-03">
            {counter}
          </Text>
          <Button
            icon={SvgChevronRight}
            size="xs"
            prominence="tertiary"
            aria-label={nextLabel}
            disabled={page >= pageCount}
            onClick={() => onPageChange(page + 1)}
          />
        </Section>
        {children}
      </Section>
    </div>
  );
}

/**
 * The step that an arrow key takes in a vertical list of pages or slides: Up
 * and the reading direction's back arrow go back one, Down and its forward
 * arrow go on one. Other keys take no step.
 */
export function listArrowStep(key: string, rtl: boolean): -1 | 0 | 1 {
  if (key === "ArrowUp" || key === (rtl ? "ArrowRight" : "ArrowLeft"))
    return -1;
  if (key === "ArrowDown" || key === (rtl ? "ArrowLeft" : "ArrowRight"))
    return 1;
  return 0;
}

const MIN_SIDEBAR_WIDTH = 88;
const MAX_SIDEBAR_WIDTH = 320;
// The most of the preview's width that the sidebar takes
const MAX_SIDEBAR_SHARE = 0.4;
const KEY_STEP = 10;

interface PreviewSidebarProps {
  // The resize handle's label
  label: string;
  initialWidth: number;
  // The preview's width (`useThumbnailColumn`); 0 when not measured
  previewWidth: number;
  hidden: boolean;
  // The thumbnails, at the sidebar's width
  children: (width: number) => ReactNode;
}

/**
 * The thumbnail column of a paged preview, as Craft's: the user drags its
 * edge, or uses the arrow keys, Home and End on it, to resize it within
 * 88px and the lesser of 320px and 40% of the preview.
 */
export function PreviewSidebar({
  label,
  initialWidth,
  previewWidth,
  hidden,
  children,
}: PreviewSidebarProps) {
  const rtl = useDirection() === "rtl";
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    width: number;
  } | null>(null);
  const [requested, setRequested] = useState(initialWidth);
  const maximum = previewWidth
    ? Math.max(
        MIN_SIDEBAR_WIDTH,
        Math.min(MAX_SIDEBAR_WIDTH, previewWidth * MAX_SIDEBAR_SHARE)
      )
    : MAX_SIDEBAR_WIDTH;
  const clamp = (value: number) =>
    Math.max(MIN_SIDEBAR_WIDTH, Math.min(maximum, value));
  const width = clamp(requested);

  const dragTo = (clientX: number) => {
    const drag = dragRef.current;
    if (!drag) return;
    setRequested(clamp(drag.width + (clientX - drag.startX) * (rtl ? -1 : 1)));
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>, apply: boolean) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    if (apply) dragTo(event.clientX);
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const resizeWithKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = rtl ? -KEY_STEP : KEY_STEP;
    const next =
      event.key === "Home"
        ? MIN_SIDEBAR_WIDTH
        : event.key === "End"
          ? maximum
          : event.key === "ArrowRight"
            ? width + step
            : event.key === "ArrowLeft"
              ? width - step
              : null;
    if (next === null) return;
    event.preventDefault();
    event.stopPropagation();
    setRequested(clamp(next));
  };

  return (
    <>
      <div
        hidden={hidden}
        style={{ width }}
        className="min-h-0 shrink-0 overflow-hidden"
      >
        {children(width)}
      </div>
      <div
        role="separator"
        hidden={hidden}
        tabIndex={hidden ? -1 : 0}
        aria-label={label}
        aria-orientation="vertical"
        aria-valuemin={MIN_SIDEBAR_WIDTH}
        aria-valuemax={Math.round(maximum)}
        aria-valuenow={Math.round(width)}
        className="group w-2 shrink-0 cursor-col-resize touch-none focus-visible:outline focus-visible:outline-1 focus-visible:outline-border-03"
        onPointerDown={(event) => {
          if (event.button !== 0 || dragRef.current) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          dragRef.current = {
            pointerId: event.pointerId,
            startX: event.clientX,
            width,
          };
        }}
        onPointerMove={(event) => {
          if (dragRef.current?.pointerId === event.pointerId)
            dragTo(event.clientX);
        }}
        onPointerUp={(event) => endDrag(event, true)}
        onPointerCancel={(event) => endDrag(event, false)}
        onLostPointerCapture={() => {
          dragRef.current = null;
        }}
        onKeyDown={resizeWithKeys}
      >
        <div className="pointer-events-none mx-auto h-full w-1 border-e border-border-02 group-hover:bg-border-01 group-focus-visible:bg-border-01" />
      </div>
    </>
  );
}
