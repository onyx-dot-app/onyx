import { useEffect, RefObject } from "react";

/**
 * A generic hook that detects clicks outside of a referenced element.
 *
 * @param ref - A ref to the element to monitor for outside clicks
 * @param callback - Function to call when a click outside is detected
 * @param enabled - Whether the hook is enabled. Defaults to true.
 *
 * @example
 * ```tsx
 * const MyComponent = () => {
 *   const ref = useRef<HTMLDivElement>(null);
 *   const [isOpen, setIsOpen] = useState(false);
 *
 *   useClickOutside(ref, () => setIsOpen(false), isOpen);
 *
 *   return (
 *     <div ref={ref}>
 *       {isOpen && <div>Content</div>}
 *     </div>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * const Dropdown = () => {
 *   const dropdownRef = useRef<HTMLDivElement>(null);
 *   const [isOpen, setIsOpen] = useState(false);
 *
 *   useClickOutside(dropdownRef, () => setIsOpen(false), isOpen);
 *
 *   return (
 *     <div>
 *       {isOpen && <div ref={dropdownRef}>Dropdown content</div>}
 *     </div>
 *   );
 * };
 * ```
 */
export function useClickOutside<T extends HTMLElement>(
  ref: RefObject<T>,
  callback: () => void,
  enabled: boolean
): void {
  useEffect(() => {
    if (!enabled) {
      return;
    }

    const handleClickOutside = (event: Event) => {
      const target = event.target as Node;

      // Check if click is outside the main ref
      if (ref.current && !ref.current.contains(target)) {
        callback();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [ref, callback, enabled]);
}

/**
 * A specialized version of useClickOutside for common modal/dropdown patterns.
 *
 * @param ref - A ref to the element to monitor for outside clicks
 * @param callback - Function to call when a click outside is detected
 * @param enabled - Whether the element is currently open/visible
 */
export function useClickOutsideWhenOpen<T extends HTMLElement>(
  ref: RefObject<T>,
  callback: () => void,
  enabled: boolean
): void {
  useClickOutside(ref, callback, enabled);
}
