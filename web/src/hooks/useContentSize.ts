import { useRef, useEffect, useState } from "react";

interface UseContentSizeOptions {
  dimension?: "width" | "height" | "both";
  dependencies?: React.DependencyList;
  observeResize?: boolean;
}

interface ContentSize {
  width: number;
  height: number;
}

export function useContentSize(
  options: UseContentSizeOptions = {}
): [React.RefObject<HTMLDivElement | null>, ContentSize] {
  const {
    dimension = "both",
    dependencies = [],
    observeResize = true,
  } = options;
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<ContentSize>({ width: 0, height: 0 });

  const measureSize = () => {
    if (ref.current) {
      const newSize: ContentSize = {
        width:
          dimension === "width" || dimension === "both"
            ? ref.current.scrollWidth
            : 0,
        height:
          dimension === "height" || dimension === "both"
            ? ref.current.scrollHeight
            : 0,
      };
      setSize(newSize);
    }
  };

  // Measure on dependencies change
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
