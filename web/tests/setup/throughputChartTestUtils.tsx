/** jsdom has no layout, so chart tests give every element one width through its bounding rect. */
import { act } from "@testing-library/react";
import type {
  CCPairThroughputResponse,
  CCPairThroughputSliceRun,
} from "@/lib/connectors/types/ccPair";

const CHART_HEIGHT = 120;

let width = 600;
const observers = new Set<TrackingResizeObserver>();

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

let restore: (() => void) | null = null;

/** Gives every element `initialWidth` until `resetChartLayout`. */
export function installChartLayout(initialWidth: number) {
  width = initialWidth;
  const originalRect = Element.prototype.getBoundingClientRect;
  const originalObserver = global.ResizeObserver;
  Element.prototype.getBoundingClientRect = rect;
  global.ResizeObserver =
    TrackingResizeObserver as unknown as typeof ResizeObserver;
  restore = () => {
    Element.prototype.getBoundingClientRect = originalRect;
    global.ResizeObserver = originalObserver;
    observers.clear();
  };
}

export function resetChartLayout() {
  restore?.();
  restore = null;
}

/** Resizes every element, as a window resize would, and notifies every observer. */
export function setChartWidth(next: number) {
  act(() => {
    width = next;
    observers.forEach((observer) => observer.notify());
  });
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

/** A 24h response of 60 slices of 24 minutes from 13:00 UTC, with the given docs and runs per slice index. */
export function throughputFixture({
  docs = {},
  runs = {},
}: {
  docs?: Record<number, number>;
  runs?: Record<number, CCPairThroughputSliceRun[]>;
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
  };
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
    if (opacityClass === null) return false;
    const opacity = Number(opacityClass[1]) / 100;
    return opacity > 0 && opacity < 1;
  });
}

/** Whether the element, or a part of it, is colored by this design token. */
export function usesToken(element: Element, token: string): boolean {
  return new RegExp(`${token}(?![-\\w])`).test(element.outerHTML);
}
