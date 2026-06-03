"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgExpand, SvgMinus, SvgPlus } from "@opal/icons";
import { cn } from "@opal/utils";
import {
  CANVAS_PADDING,
  NODE_HEIGHT,
  NODE_WIDTH,
  layoutFlow,
} from "@/app/flows/graphLayout";
import { FlowNodeCard } from "@/app/flows/components/FlowNodeCard";
import { MAX_ZOOM, MIN_ZOOM, ZOOM_STEP } from "@/app/flows/constants";
import type { FlowNodeRunStatus, FlowSpec } from "@/app/flows/types";

interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface FlowCanvasProps {
  spec: FlowSpec;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  /** Per-node status, supplied by the run inspector and empty while editing. */
  runStatusByNode?: Record<string, FlowNodeRunStatus>;
  className?: string;
}

function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

/**
 * The flow graph, pannable and zoomable.
 *
 * Positions come from `layoutFlow`, so this component only has to place what
 * it is handed and manage the viewport. Nodes and edges share one transformed
 * layer, which is what keeps an edge glued to its node at every zoom level
 * instead of drifting a pixel at a time.
 */
export function FlowCanvas({
  spec,
  selectedNodeId,
  onSelectNode,
  runStatusByNode,
  className,
}: FlowCanvasProps) {
  const t = useTranslations("flows.canvas");
  const containerRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, zoom: 1 });

  const layout = useMemo(() => layoutFlow(spec), [spec]);

  const fitToView = useCallback(() => {
    const container = containerRef.current;
    if (container === null || layout.width === 0 || layout.height === 0) return;

    const { width, height } = container.getBoundingClientRect();
    if (width === 0 || height === 0) return;

    // Never zoom past 1 when fitting: a two-node flow blown up to fill the
    // pane looks broken rather than generous.
    const zoom = clampZoom(
      Math.min(1, width / layout.width, height / layout.height)
    );
    setViewport({
      x: (width - layout.width * zoom) / 2,
      y: (height - layout.height * zoom) / 2,
      zoom,
    });
  }, [layout.width, layout.height]);

  // Re-fit when the graph's extent changes, not on every spec keystroke —
  // otherwise renaming a node would yank the viewport out from under you.
  // A ResizeObserver covers the first paint, where the container still
  // measures zero and an unguarded fit would silently do nothing.
  useEffect(() => {
    const container = containerRef.current;
    if (container === null) return;

    fitToView();
    const observer = new ResizeObserver(() => fitToView());
    observer.observe(container);
    return () => observer.disconnect();
  }, [fitToView]);

  const zoomBy = useCallback((factor: number) => {
    const container = containerRef.current;
    if (container === null) return;
    const { width, height } = container.getBoundingClientRect();
    setViewport((current) =>
      zoomAround(current, factor, width / 2, height / 2)
    );
  }, []);

  // Bound by hand rather than through `onWheel`. React registers wheel
  // listeners as passive, so `preventDefault` there is ignored with a console
  // warning and the page scrolls away underneath the zoom.
  useEffect(() => {
    const container = containerRef.current;
    if (container === null) return;

    function onWheel(event: WheelEvent) {
      if (container === null) return;
      event.preventDefault();

      const bounds = container.getBoundingClientRect();
      const factor = event.deltaY < 0 ? 1 + ZOOM_STEP : 1 - ZOOM_STEP;
      setViewport((current) =>
        zoomAround(
          current,
          factor,
          event.clientX - bounds.left,
          event.clientY - bounds.top
        )
      );
    }

    container.addEventListener("wheel", onWheel, { passive: false });
    return () => container.removeEventListener("wheel", onWheel);
  }, []);

  const panOrigin = useRef<{ x: number; y: number } | null>(null);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // Anything but a node pans. Comparing target to currentTarget is not
      // enough: the transformed layer covers the whole graph area, so the
      // empty space between nodes belongs to it rather than the container.
      if (
        event.target instanceof Element &&
        event.target.closest("[data-flow-node]") !== null
      ) {
        return;
      }
      event.currentTarget.setPointerCapture(event.pointerId);
      panOrigin.current = {
        x: event.clientX - viewport.x,
        y: event.clientY - viewport.y,
      };
      onSelectNode(null);
    },
    [viewport.x, viewport.y, onSelectNode]
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const origin = panOrigin.current;
      if (origin === null) return;
      setViewport((current) => ({
        ...current,
        x: event.clientX - origin.x,
        y: event.clientY - origin.y,
      }));
    },
    []
  );

  const endPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (panOrigin.current === null) return;
    panOrigin.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  return (
    <div
      className={cn(
        "relative overflow-hidden bg-background-tint-01 rounded-12",
        className
      )}
    >
      <div
        ref={containerRef}
        data-testid="flow-canvas"
        role="presentation"
        className="w-full h-full touch-none cursor-grab active:cursor-grabbing"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endPan}
        onPointerCancel={endPan}
      >
        <div
          className="absolute top-0 start-0 origin-top-left"
          style={{
            transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
            width: layout.width,
            height: layout.height,
          }}
        >
          <svg
            width={layout.width}
            height={layout.height}
            className="absolute top-0 start-0 pointer-events-none overflow-visible"
            aria-hidden
          >
            {layout.edges.map((edge) => (
              <g
                key={edge.id}
                className={
                  edge.branch === "true"
                    ? "text-status-success-05"
                    : edge.branch === "false"
                      ? "text-status-error-05"
                      : "text-border-02"
                }
              >
                <path
                  d={edge.path}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                />
                {/* A dot where the edge lands, rather than an SVG marker:
                    markers do not inherit `currentColor`, so each branch
                    colour would need its own definition. */}
                <circle
                  cx={edge.endX}
                  cy={edge.endY}
                  r={3}
                  fill="currentColor"
                />
                {edge.branch !== null ? (
                  <text
                    x={edge.labelX}
                    y={edge.labelY - 6}
                    textAnchor="middle"
                    fill="currentColor"
                    className="font-figure-small-label"
                  >
                    {t(`branch.${edge.branch}`)}
                  </text>
                ) : null}
              </g>
            ))}
          </svg>

          {layout.nodes.map((placed) => (
            <FlowNodeCard
              key={placed.node.id}
              node={placed.node}
              x={placed.x}
              y={placed.y}
              selected={placed.node.id === selectedNodeId}
              reachable={placed.reachable}
              isStart={placed.node.id === spec.start}
              runStatus={runStatusByNode?.[placed.node.id] ?? null}
              onSelect={onSelectNode}
            />
          ))}
        </div>
      </div>

      <div className="absolute bottom-3 end-3 flex flex-row items-center gap-1 p-1 rounded-12 bg-background-neutral-00 border border-border-01">
        <Button
          variant="default"
          prominence="secondary"
          size="sm"
          icon={SvgMinus}
          tooltip={t("controls.zoomOut")}
          aria-label={t("controls.zoomOut")}
          onClick={() => zoomBy(1 - ZOOM_STEP)}
        />
        <Text font="figure-small-value" color="text-03">
          {`${Math.round(viewport.zoom * 100)}%`}
        </Text>
        <Button
          variant="default"
          prominence="secondary"
          size="sm"
          icon={SvgPlus}
          tooltip={t("controls.zoomIn")}
          aria-label={t("controls.zoomIn")}
          onClick={() => zoomBy(1 + ZOOM_STEP)}
        />
        <Button
          variant="default"
          prominence="secondary"
          size="sm"
          icon={SvgExpand}
          tooltip={t("controls.fit")}
          aria-label={t("controls.fit")}
          onClick={fitToView}
        />
      </div>
    </div>
  );
}

/**
 * Zoom while holding one screen point still.
 *
 * Without the compensating translate, zooming walks the graph off toward a
 * corner and you spend the next few seconds panning back.
 */
function zoomAround(
  current: Viewport,
  factor: number,
  originX: number,
  originY: number
): Viewport {
  const zoom = clampZoom(current.zoom * factor);
  const ratio = zoom / current.zoom;
  return {
    zoom,
    x: originX - (originX - current.x) * ratio,
    y: originY - (originY - current.y) * ratio,
  };
}

export const CANVAS_GEOMETRY = { NODE_WIDTH, NODE_HEIGHT, CANVAS_PADDING };
