import { useLayoutEffect } from "react";

/**
 * Publishes an element's height as a CSS variable on its parent, so the
 * parent's other children can keep clear of it. The first value is set
 * before paint.
 */
export default function usePublishedHeight(
  element: HTMLElement | null,
  variable: string
) {
  useLayoutEffect(() => {
    const host = element?.parentElement;
    if (!element || !host) return;

    const update = () =>
      host.style.setProperty(
        variable,
        `${element.getBoundingClientRect().height}px`
      );
    update();

    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => {
      observer.disconnect();
      host.style.removeProperty(variable);
    };
  }, [element, variable]);
}
