"use client";

import { useRef, useEffect, useState } from "react";

interface ContentSize {
  width: number;
  height: number;
}

/**
 * A hook that measures the content size (scrollWidth/scrollHeight) of a DOM element.
 *
 * This hook measures the natural content size of an element including overflow,
 * which is useful for determining how much space content needs before wrapping
 * or being cut off. It can automatically track size changes via ResizeObserver
 * and/or re-measure when dependencies change.
 *
 * @param dependencies - Optional dependency array to trigger re-measurement when values change
 * @param observeResize - Whether to continuously observe size changes via ResizeObserver. Defaults to true.
 *
 * @returns A tuple containing:
 *   - `ref`: A ref object to attach to the element you want to measure
 *   - `size`: An object with `width` and `height` properties (in pixels)
 *
 * @example
 * ```tsx
 * // Basic usage - measure button content to determine if it needs to wrap
 * const MyButton = ({ children }) => {
 *   const [ref, { width }] = useContentSize();
 *
 *   return (
 *     <button ref={ref}>
 *       Content is {width}px wide
 *     </button>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // Measure content when it changes
 * const DynamicContent = ({ text }) => {
 *   const [ref, { width, height }] = useContentSize([text]);
 *
 *   return (
 *     <div ref={ref}>
 *       {text}
 *       <p>Size: {width}x{height}</p>
 *     </div>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // Measure once without observing resize (better performance)
 * const SelectButton = ({ children }) => {
 *   const content = useMemo(() => <span>{children}</span>, [children]);
 *   const [measureRef, { width: contentWidth }] = useContentSize([content], false);
 *
 *   return (
 *     <div>
 *       // Hidden element for measurement
 *       <div ref={measureRef} style={{ position: 'absolute', visibility: 'hidden' }}>
 *         {content}
 *       </div>
 *       // Actual button with calculated width
 *       <button style={{ width: contentWidth }}>
 *         {content}
 *       </button>
 *     </div>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // Auto-expanding textarea
 * const AutoExpandingTextarea = () => {
 *   const [value, setValue] = useState('');
 *   const [ref, { height }] = useContentSize([value]);
 *
 *   return (
 *     <textarea
 *       ref={ref}
 *       value={value}
 *       onChange={(e) => setValue(e.target.value)}
 *       style={{ height: `${height}px` }}
 *     />
 *   );
 * };
 * ```
 */
export function useContentSize(
  dependencies?: React.DependencyList,
  observeResize: boolean = true
): [React.RefObject<HTMLDivElement | null>, ContentSize] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<ContentSize>({ width: 0, height: 0 });

  const measureSize = () => {
    if (ref.current) {
      const newSize: ContentSize = {
        width: ref.current.scrollWidth,
        height: ref.current.scrollHeight,
      };
      setSize(newSize);
    }
  };

  // Measure on dependencies change
  // We intentionally use the `dependencies` parameter directly as the dependency array.
  // The exhaustive-deps rule is disabled because:
  // 1. `measureSize` is stable (doesn't change) and doesn't need to be in the deps
  // 2. We want to re-measure ONLY when the caller's dependencies change, not when measureSize changes
  // 3. The caller passes their own dependency array to control when measurement happens
  useEffect(() => {
    measureSize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);

  // Observe resize if enabled
  useEffect(() => {
    if (!observeResize || !ref.current) return;

    const resizeObserver = new ResizeObserver(() => {
      // Use requestAnimationFrame to ensure measurements happen after the resize is complete
      requestAnimationFrame(() => {
        measureSize();
      });
    });

    // Observe the container itself
    resizeObserver.observe(ref.current);

    // Also observe all descendant elements (like textareas)
    const descendants = ref.current.querySelectorAll("*");
    descendants.forEach((el) => {
      resizeObserver.observe(el);
    });

    return () => {
      resizeObserver.disconnect();
    };
  }, [observeResize]);

  return [ref, size];
}
