import { useEffect, useRef, useState } from "react";

export function useMouseTracking() {
  const [isHovering, setIsHovering] = useState<boolean>(false);
  const trackedElementRef = useRef<HTMLDivElement>(null);
  const hoverElementRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      if (trackedElementRef.current && hoverElementRef.current) {
        const trackedRect = trackedElementRef.current.getBoundingClientRect();
        const hoverRect = hoverElementRef.current.getBoundingClientRect();

        const isOverTracked =
          event.clientX >= trackedRect.left &&
          event.clientX <= trackedRect.right &&
          event.clientY >= trackedRect.top &&
          event.clientY <= trackedRect.bottom;

        const isOverHover =
          event.clientX >= hoverRect.left &&
          event.clientX <= hoverRect.right &&
          event.clientY >= hoverRect.top &&
          event.clientY <= hoverRect.bottom;

        setIsHovering(isOverTracked || isOverHover);
      }
    };

    document.addEventListener("mousemove", handleMouseMove);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
    };
  }, []);

  return { isHovering, trackedElementRef, hoverElementRef };
}
