"use client";

/**
 * useColumnWidths — Proportional column widths with splitter resize.
 *
 * WHY NOT TANSTACK'S BUILT-IN COLUMN SIZING?
 *
 * TanStack Table's column resize system (columnSizing state,
 * header.getResizeHandler(), columnResizeMode) doesn't support the
 * behavior our design requires:
 *
 * 1. No proportional fill — TanStack uses absolute pixel widths from
 *    columnDef.size. When the container is wider than the sum of sizes,
 *    the extra space is not distributed. We need weight-based proportional
 *    distribution so columns fill the container at any width.
 *
 * 2. No splitter semantics — TanStack's resize changes one column's size
 *    in isolation (the total table width grows/shrinks). We need "splitter"
 *    behavior: dragging column i's right edge grows column i and shrinks
 *    column i+1 by the same amount, keeping the total fixed. This prevents
 *    the actions column from jittering.
 *
 * 3. No per-column min-width enforcement during drag — TanStack only has a
 *    global minSize default. We enforce per-column min-widths and clamp the
 *    drag delta so neither the dragged column nor its neighbor can shrink
 *    below their floor.
 *
 * 4. No weight-based resize persistence — TanStack stores absolute pixel
 *    deltas. When the window resizes after a column drag, the proportions
 *    drift. We store weights, so a user-resized column scales proportionally
 *    with the container — the ratio is preserved, not the pixel count.
 *
 * APPROACH:
 *
 * We still rely on TanStack for everything else (sorting, pagination,
 * visibility, row selection). Only column width computation and resize
 * interaction are handled here. The columnDef.size values are used as
 * initial weights, and TanStack's enableResizing / getCanResize() flags
 * are still respected in the render loop.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { Header } from "@tanstack/react-table";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Extracted config ready to pass to useColumnWidths. */
export interface WidthConfig {
  fixedColumnIds: Set<string>;
  columnWeights: Record<string, number>;
  columnMinWidths: Record<string, number>;
}

interface UseColumnWidthsOptions {
  /** Visible headers from TanStack's first header group. */
  headers: Header<any, unknown>[];
  /** Column IDs that have fixed pixel widths (e.g. qualifier, actions). */
  fixedColumnIds: Set<string>;
  /** Explicit column weights (takes precedence over columnDef.size). */
  columnWeights?: Record<string, number>;
  /** Per-column minimum widths for data (non-fixed) columns. */
  columnMinWidths: Record<string, number>;
}

interface UseColumnWidthsReturn {
  /** Attach to the scrollable container for width measurement. */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** Computed pixel widths keyed by column ID. */
  columnWidths: Record<string, number>;
  /** Factory to create a splitter resize handler for a column pair. */
  createResizeHandler: (
    columnId: string,
    neighborId: string
  ) => (event: React.MouseEvent | React.TouchEvent) => void;
}

// ---------------------------------------------------------------------------
// Internal: measure container width via ResizeObserver
// ---------------------------------------------------------------------------

/** Tracks an element's content width via ResizeObserver, returning a ref and the current width. */
function useElementWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

// ---------------------------------------------------------------------------
// Pure function: compute pixel widths from weights
// ---------------------------------------------------------------------------

/** Converts column weights into pixel widths, enforcing per-column minimums and fixed-column sizes. */
function computeColumnWidths(
  containerWidth: number,
  headers: Header<any, unknown>[],
  customWeights: Record<string, number>,
  fixedColumnIds: Set<string>,
  columnWeights: Record<string, number>,
  columnMinWidths: Record<string, number>
): Record<string, number> {
  const result: Record<string, number> = {};

  let fixedTotal = 0;
  const dataColumns: { id: string; weight: number; minWidth: number }[] = [];

  for (const h of headers) {
    const baseSize = h.column.columnDef.size ?? 20;
    if (fixedColumnIds.has(h.id)) {
      fixedTotal += baseSize;
    } else {
      dataColumns.push({
        id: h.id,
        weight: customWeights[h.id] ?? columnWeights[h.id] ?? baseSize,
        minWidth: columnMinWidths[h.id] ?? 50,
      });
    }
  }

  const tableMinWidth =
    fixedTotal + dataColumns.reduce((sum, col) => sum + col.minWidth, 0);
  const tableWidth =
    containerWidth > 0 ? Math.max(containerWidth, tableMinWidth) : 0;

  if (tableWidth === 0) {
    for (const h of headers) {
      result[h.id] = h.column.columnDef.size ?? 20;
    }
    return result;
  }

  const available = tableWidth - fixedTotal;
  const totalWeight = dataColumns.reduce((sum, col) => sum + col.weight, 0);

  // Proportional allocation with min-width clamping
  let clampedTotal = 0;
  let unclampedWeight = 0;
  const clamped = new Set<string>();

  for (const col of dataColumns) {
    const proportional = available * (col.weight / totalWeight);
    if (proportional < col.minWidth) {
      result[col.id] = col.minWidth;
      clampedTotal += col.minWidth;
      clamped.add(col.id);
    } else {
      unclampedWeight += col.weight;
    }
  }

  // Distribute remaining space among unclamped columns
  const remainingSpace = available - clampedTotal;
  let assigned = 0;
  const unclampedCols = dataColumns.filter((col) => !clamped.has(col.id));

  for (let i = 0; i < unclampedCols.length; i++) {
    const col = unclampedCols[i]!;
    if (i === unclampedCols.length - 1) {
      result[col.id] = remainingSpace - assigned;
    } else {
      const w = Math.round(remainingSpace * (col.weight / unclampedWeight));
      result[col.id] = w;
      assigned += w;
    }
  }

  // Fixed columns keep their base size
  for (const h of headers) {
    if (fixedColumnIds.has(h.id)) {
      result[h.id] = h.column.columnDef.size ?? 20;
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Pure function: create a splitter resize handler for a column pair
// ---------------------------------------------------------------------------

/** Creates a mouse/touch drag handler that redistributes weight between two adjacent columns. */
function createSplitterResizeHandler(
  columnId: string,
  neighborId: string,
  startColumnWidth: number,
  startNeighborWidth: number,
  startColumnWeight: number,
  startNeighborWeight: number,
  columnMinWidth: number,
  neighborMinWidth: number,
  setter: (value: React.SetStateAction<Record<string, number>>) => void
): (event: React.MouseEvent | React.TouchEvent) => void {
  return (event: React.MouseEvent | React.TouchEvent) => {
    const startX =
      "touches" in event ? event.touches[0]!.clientX : event.clientX;

    const onMove = (e: MouseEvent | TouchEvent) => {
      const currentX =
        "touches" in e
          ? (e as TouchEvent).touches[0]!.clientX
          : (e as MouseEvent).clientX;
      const rawDelta = currentX - startX;
      const minDelta = columnMinWidth - startColumnWidth;
      const maxDelta = startNeighborWidth - neighborMinWidth;
      const delta = Math.max(minDelta, Math.min(maxDelta, rawDelta));

      setter((prev) => ({
        ...prev,
        [columnId]:
          startColumnWeight * ((startColumnWidth + delta) / startColumnWidth),
        [neighborId]:
          startNeighborWeight *
          ((startNeighborWidth - delta) / startNeighborWidth),
      }));
    };

    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };

    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchmove", onMove);
    document.addEventListener("touchend", onUp);
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Computes proportional column pixel widths from weights and provides
 * splitter-style resize handlers that keep total table width constant.
 *
 * @example
 * ```tsx
 * const { containerRef, columnWidths, createResizeHandler } = useColumnWidths({
 *   headers: table.getHeaderGroups()[0].headers,
 *   fixedColumnIds: new Set(["actions"]),
 *   columnMinWidths: { name: 120, status: 80 },
 * });
 * ```
 */
export default function useColumnWidths({
  headers,
  fixedColumnIds,
  columnWeights = {},
  columnMinWidths,
}: UseColumnWidthsOptions): UseColumnWidthsReturn {
  const [containerRef, containerWidth] = useElementWidth();
  const [customWeights, setCustomWeights] = useState<Record<string, number>>(
    {}
  );

  const columnWidths = computeColumnWidths(
    containerWidth,
    headers,
    customWeights,
    fixedColumnIds,
    columnWeights,
    columnMinWidths
  );

  const createResizeHandler = useCallback(
    (columnId: string, neighborId: string) => {
      const header = headers.find((h) => h.id === columnId);
      const neighbor = headers.find((h) => h.id === neighborId);

      return createSplitterResizeHandler(
        columnId,
        neighborId,
        columnWidths[columnId] ?? 0,
        columnWidths[neighborId] ?? 0,
        customWeights[columnId] ??
          columnWeights[columnId] ??
          header?.column.columnDef.size ??
          20,
        customWeights[neighborId] ??
          columnWeights[neighborId] ??
          neighbor?.column.columnDef.size ??
          20,
        columnMinWidths[columnId] ?? 50,
        columnMinWidths[neighborId] ?? 50,
        setCustomWeights
      );
    },
    [headers, columnWidths, customWeights, columnWeights, columnMinWidths]
  );

  return { containerRef, columnWidths, createResizeHandler };
}
