"use client";

import { useEffect, RefObject } from "react";

/**
 * A generic hook that detects clicks outside of referenced element(s).
 *
 * @param ref - A ref or array of refs to monitor for outside clicks
 * @param callback - Function to call when a click outside is detected
 * @param enabled - Whether the hook is enabled. Defaults to true.
 *
 * @example
 * ```tsx
 * // Single ref example
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
 * // Single ref example with dropdown
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
 *
 * @example
 * ```tsx
 * // Multiple refs example - useful for combobox/dropdown with separate input and menu
 * const ComboBox = () => {
 *   const inputRef = useRef<HTMLInputElement>(null);
 *   const dropdownRef = useRef<HTMLDivElement>(null);
 *   const [isOpen, setIsOpen] = useState(false);
 *
 *   // Close dropdown only if click is outside BOTH input and dropdown
 *   useClickOutside([inputRef, dropdownRef], () => setIsOpen(false), isOpen);
 *
 *   return (
 *     <div>
 *       <input ref={inputRef} onClick={() => setIsOpen(true)} />
 *       {isOpen && (
 *         <div ref={dropdownRef}>
 *           <div>Option 1</div>
 *           <div>Option 2</div>
 *         </div>
 *       )}
 *     </div>
 *   );
 * };
 * ```
 */
export function useClickOutside<T extends HTMLElement>(
  ref: RefObject<T> | RefObject<T>[] | null,
  callback: () => void,
  enabled: boolean = true
): void {
  useEffect(() => {
    if (!enabled) {
      return;
    }

    const handleClickOutside = (event: Event) => {
      const target = event.target as Node;

      // Normalize to array for consistent handling
      const refs = Array.isArray(ref) ? ref : [ref];

      // Check if click is outside all provided refs
      const isOutside = refs.every(
        (r) => !r?.current || !r.current.contains(target)
      );

      if (isOutside) {
        callback();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [ref, callback, enabled]);
}
