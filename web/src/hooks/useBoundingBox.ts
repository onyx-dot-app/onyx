import { useRef, useEffect, useCallback, useState } from "react";

export function useBoundingBox() {
  const ref = useRef<HTMLDivElement>(null);
  const [inside, setInside] = useState(false);

  const checkMousePosition = useCallback((event: MouseEvent) => {
    if (!ref.current) return;

    const rect = ref.current.getBoundingClientRect();
    const isInside =
      event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom;

    setInside(isInside);
  }, []);

  useEffect(() => {
    // Set up event listeners for mouse movement
    const handleMouseMove = (event: MouseEvent) => checkMousePosition(event);

    document.addEventListener("mousemove", handleMouseMove);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
    };
  }, [checkMousePosition]);

  return { ref, inside };
}
