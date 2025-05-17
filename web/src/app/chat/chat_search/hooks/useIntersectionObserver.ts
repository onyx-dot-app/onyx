import { useEffect, useRef } from "react";

interface UseIntersectionObserverOptions {
  root?: Element | null;
  rootMargin?: string;
  threshold?: number;
  onIntersect: () => void;
  enabled?: boolean;
}

export function useIntersectionObserver({
  root = null,
  rootMargin = "0px",
  threshold = 0.1,
  onIntersect,
  enabled = true,
}: UseIntersectionObserverOptions) {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const options = {
      root,
      rootMargin,
      threshold,
    };

    const observer = new IntersectionObserver((entries) => {
      const [entry] = entries;
      if (entry !== undefined && entry.isIntersecting) {
        onIntersect();
      }
    }, options);

    if (targetRef.current) {
      observer.observe(targetRef.current);
    }

    observerRef.current = observer;

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [root, rootMargin, threshold, onIntersect, enabled]);

  return { targetRef };
}
