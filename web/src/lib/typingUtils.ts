import { useEffect } from "react";

type Handler = (event: React.KeyboardEvent) => void;

export function handleKeyPress(
  requestedKey: string,
  callback?: Handler,
  passthrough?: Handler
): Handler {
  return (event) => {
    const func = event.key === requestedKey ? callback : passthrough;
    func?.(event);
  };
}

export function handleEnterPress(
  callback?: Handler,
  passthrough?: Handler
): Handler {
  return handleKeyPress("Enter", callback, passthrough);
}

export function useEscapePress(callback: () => void, enabled?: boolean) {
  useEffect(() => {
    if (!enabled) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        callback();
      }
    };

    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("keydown", handleEscape);
    };
  }, [callback, enabled]);
}
