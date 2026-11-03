/** jsdom has no layout, so chart tests give every element one width however the chart measures it. */
import {
  cloneElement,
  useEffect,
  useSyncExternalStore,
  type ReactElement,
} from "react";
import { act } from "@testing-library/react";
import type { CCPairThroughputResponse } from "@/lib/connectors/types/ccPair";

const CHART_HEIGHT = 120;

let width = 600;
const listeners = new Set<() => void>();
const observers = new Set<TrackingResizeObserver>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function rect(): DOMRect {
  return {
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    width,
    height: CHART_HEIGHT,
    right: width,
    bottom: CHART_HEIGHT,
    toJSON: () => ({}),
  } as DOMRect;
}

class TrackingResizeObserver {
  private targets = new Set<Element>();
  constructor(private callback: ResizeObserverCallback) {
    observers.add(this);
  }
  observe(target: Element) {
    this.targets.add(target);
    this.notify();
  }
  unobserve(target: Element) {
    this.targets.delete(target);
  }
  disconnect() {
    this.targets.clear();
    observers.delete(this);
  }
  notify() {
    const entries = Array.from(this.targets).map((target) => ({
      target,
      contentRect: rect(),
      borderBoxSize: [{ inlineSize: width, blockSize: CHART_HEIGHT }],
      contentBoxSize: [{ inlineSize: width, blockSize: CHART_HEIGHT }],
      devicePixelContentBoxSize: [
        { inlineSize: width, blockSize: CHART_HEIGHT },
      ],
    }));
    if (entries.length > 0) {
      this.callback(
        entries as unknown as ResizeObserverEntry[],
        this as unknown as ResizeObserver
      );
    }
  }
}

const SIZE_PROPS = [
  ["clientWidth", () => width],
  ["offsetWidth", () => width],
  ["scrollWidth", () => width],
  ["clientHeight", () => CHART_HEIGHT],
  ["offsetHeight", () => CHART_HEIGHT],
] as const;

let restore: (() => void) | null = null;

/** Gives every element `initialWidth` until `resetChartLayout`. */
export function installChartLayout(initialWidth: number) {
  width = initialWidth;
  const originalRect = Element.prototype.getBoundingClientRect;
  const originalObserver = global.ResizeObserver;
  const originalSizes = SIZE_PROPS.map(
    ([name]) =>
      [
        name,
        Object.getOwnPropertyDescriptor(HTMLElement.prototype, name),
      ] as const
  );
  Element.prototype.getBoundingClientRect = rect;
  global.ResizeObserver =
    TrackingResizeObserver as unknown as typeof ResizeObserver;
  for (const [name, get] of SIZE_PROPS) {
    Object.defineProperty(HTMLElement.prototype, name, {
      configurable: true,
      get,
    });
  }
  restore = () => {
    Element.prototype.getBoundingClientRect = originalRect;
    global.ResizeObserver = originalObserver;
    for (const [name, descriptor] of originalSizes) {
      if (descriptor === undefined) {
        delete (HTMLElement.prototype as unknown as Record<string, unknown>)[
          name
        ];
      } else {
        Object.defineProperty(HTMLElement.prototype, name, descriptor);
      }
    }
    observers.clear();
    listeners.clear();
  };
}

export function resetChartLayout() {
  restore?.();
  restore = null;
}

/** Resizes every element, as a window resize would, and tells every way of listening. */
export function setChartWidth(next: number) {
  act(() => {
    width = next;
    listeners.forEach((listener) => listener());
    observers.forEach((observer) => observer.notify());
    window.dispatchEvent(new Event("resize"));
  });
}

interface MockResponsiveContainerProps {
  children: ReactElement<{ width?: number; height?: number }>;
  height?: number | string;
  onResize?: (width: number, height: number) => void;
}

function MockResponsiveContainer({
  children,
  height,
  onResize,
}: MockResponsiveContainerProps) {
  const current = useSyncExternalStore(
    subscribe,
    () => width,
    () => width
  );
  const resolvedHeight = typeof height === "number" ? height : CHART_HEIGHT;
  useEffect(() => {
    onResize?.(current, resolvedHeight);
  }, [current, resolvedHeight, onResize]);
  return cloneElement(children, { width: current, height: resolvedHeight });
}

/** The `jest.mock("recharts", ...)` factory: real recharts with a sized container. */
export function mockRecharts() {
  const actual = jest.requireActual<typeof import("recharts")>("recharts");
  return { ...actual, ResponsiveContainer: MockResponsiveContainer };
}

export interface SliceRunFixture {
  attempt_id: number;
  status:
    | "in_progress"
    | "failed"
    | "completed_with_errors"
    | "success"
    | "canceled";
  resolved: boolean;
}

export const FIXTURE_START = Date.UTC(2026, 9, 29, 13, 0);
export const FIXTURE_SLICE_MS = 24 * 60_000;
export const FIXTURE_BINS = 60;

export function sliceStart(index: number): number {
  return FIXTURE_START + index * FIXTURE_SLICE_MS;
}

export function sliceEnd(index: number): number {
  return sliceStart(index + 1);
}

/** A 24h response of 60 clock-aligned slices with the given docs and runs per slice index. */
export function throughputFixture({
  docs = {},
  runs = {},
}: {
  docs?: Record<number, number>;
  runs?: Record<number, SliceRunFixture[]>;
} = {}): CCPairThroughputResponse {
  const slices = Array.from({ length: FIXTURE_BINS }, (_, index) => ({
    start: new Date(sliceStart(index)).toISOString(),
    end: new Date(sliceEnd(index)).toISOString(),
    docs_indexed: docs[index] ?? 0,
    runs: runs[index] ?? [],
  }));
  return {
    window_start: new Date(sliceStart(0)).toISOString(),
    window_end: new Date(sliceEnd(FIXTURE_BINS - 1)).toISOString(),
    docs_indexed: slices.map((slice) => slice.docs_indexed),
    runs: [],
    slices,
  } as CCPairThroughputResponse;
}

/** Whether the element, a part of it or a wrapper inside `root` is drawn partly transparent. Fully transparent hit areas are not fades. */
export function isFaded(element: Element, root: Element): boolean {
  const chain: Element[] = [
    element,
    ...Array.from(element.querySelectorAll("*")),
  ];
  for (let node = element.parentElement; node && node !== root;) {
    chain.push(node);
    node = node.parentElement;
  }
  return chain.some((node) => {
    const opacityClass = /(?:^|\s)opacity-(\d+)(?:\s|$)/.exec(
      node.getAttribute("class") ?? ""
    );
    if (opacityClass !== null && isPartial(Number(opacityClass[1]) / 100)) {
      return true;
    }
    const style = (node as HTMLElement).style;
    if (style?.opacity !== undefined && style.opacity !== "") {
      if (isPartial(Number(style.opacity))) return true;
    }
    return ["opacity", "fill-opacity", "stroke-opacity"].some((attribute) => {
      const value = node.getAttribute(attribute);
      return value !== null && isPartial(Number(value));
    });
  });
}

function isPartial(opacity: number): boolean {
  return opacity > 0 && opacity < 1;
}

/** Whether the element, or a part of it, is colored by this design token. */
export function usesToken(element: Element, token: string): boolean {
  return new RegExp(`${token}(?![-\\w])`).test(element.outerHTML);
}
