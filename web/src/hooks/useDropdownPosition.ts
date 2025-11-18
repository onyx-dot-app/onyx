import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  RefObject,
} from "react";
import { debounce } from "lodash";

// =============================================================================
// Types
// =============================================================================

export interface DropdownPosition {
  top: number;
  left: number;
  width: number | null;
  flipped: boolean;
}

export interface UseDropdownPositionOptions {
  /** Whether the dropdown is currently open */
  isOpen: boolean;
  /** Maximum height of the dropdown in pixels. Defaults to 240 */
  dropdownHeight?: number;
  /** Gap between trigger element and dropdown in pixels. Defaults to 4 */
  gap?: number;
  /** Minimum distance from viewport edge in pixels. Defaults to 8 */
  viewportPadding?: number;
  /** Whether dropdown width should match trigger width. Defaults to true */
  matchWidth?: boolean;
  /** Custom dropdown width when matchWidth is false. Defaults to null */
  customWidth?: number | null;
  /** Debounce delay in milliseconds for scroll/resize events. Defaults to 16 (~60fps) */
  debounceDelay?: number;
}

// =============================================================================
// Hook
// =============================================================================

/**
 * A reusable hook for positioning dropdowns/popovers with smart collision detection.
 *
 * Features:
 * - Automatic vertical flipping when near viewport edges
 * - Horizontal boundary constraints to keep dropdown in viewport
 * - Updates position on scroll and resize (debounced for performance)
 * - Configurable dimensions, spacing, and behavior
 * - Returns position object and ref to attach to trigger element
 *
 * @param options - Configuration options for dropdown positioning
 * @returns Object containing dropdown position and container ref
 *
 * @example
 * ```tsx
 * // Basic usage - ComboBox/Select dropdown
 * const MySelect = () => {
 *   const [isOpen, setIsOpen] = useState(false);
 *   const { dropdownPosition, containerRef } = useDropdownPosition({ isOpen });
 *
 *   return (
 *     <div ref={containerRef}>
 *       <button onClick={() => setIsOpen(!isOpen)}>
 *         Select option
 *       </button>
 *       {isOpen && dropdownPosition && (
 *         <Portal>
 *           <div
 *             style={{
 *               position: 'absolute',
 *               top: dropdownPosition.top,
 *               left: dropdownPosition.left,
 *               width: dropdownPosition.width,
 *             }}
 *           >
 *             <div>Option 1</div>
 *             <div>Option 2</div>
 *           </div>
 *         </Portal>
 *       )}
 *     </div>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // With custom dimensions - Context menu
 * const ContextMenu = () => {
 *   const [isOpen, setIsOpen] = useState(false);
 *   const { dropdownPosition, containerRef } = useDropdownPosition({
 *     isOpen,
 *     dropdownHeight: 300,    // Taller menu
 *     gap: 8,                  // More spacing
 *     matchWidth: false,       // Don't match trigger width
 *     customWidth: 200,        // Fixed 200px width
 *   });
 *
 *   return (
 *     <div ref={containerRef} onContextMenu={(e) => {
 *       e.preventDefault();
 *       setIsOpen(true);
 *     }}>
 *       Right click me
 *       {isOpen && dropdownPosition && (
 *         <Portal>
 *           <div
 *             style={{
 *               position: 'absolute',
 *               top: dropdownPosition.top,
 *               left: dropdownPosition.left,
 *               width: dropdownPosition.width || 200,
 *             }}
 *           >
 *             <div>Copy</div>
 *             <div>Paste</div>
 *             <div>Delete</div>
 *           </div>
 *         </Portal>
 *       )}
 *     </div>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // With flipped state indicator - Tooltip/Popover
 * const Popover = ({ children, content }) => {
 *   const [isOpen, setIsOpen] = useState(false);
 *   const { dropdownPosition, containerRef } = useDropdownPosition({
 *     isOpen,
 *     dropdownHeight: 150,
 *     gap: 12,
 *     matchWidth: false,
 *   });
 *
 *   return (
 *     <div ref={containerRef}>
 *       <button onClick={() => setIsOpen(!isOpen)}>
 *         {children}
 *       </button>
 *       {isOpen && dropdownPosition && (
 *         <Portal>
 *           <div
 *             className={cn(
 *               "absolute",
 *               dropdownPosition.flipped ? "arrow-bottom" : "arrow-top"
 *             )}
 *             style={{
 *               top: dropdownPosition.top,
 *               left: dropdownPosition.left,
 *             }}
 *           >
 *             {content}
 *           </div>
 *         </Portal>
 *       )}
 *     </div>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // Date picker with custom configuration
 * const DatePicker = () => {
 *   const [isOpen, setIsOpen] = useState(false);
 *   const { dropdownPosition, containerRef } = useDropdownPosition({
 *     isOpen,
 *     dropdownHeight: 320,     // Calendar height
 *     gap: 6,
 *     viewportPadding: 16,     // More padding from edges
 *     matchWidth: false,
 *     debounceDelay: 100,      // Less aggressive updates
 *   });
 *
 *   return (
 *     <div ref={containerRef}>
 *       <input
 *         type="text"
 *         onClick={() => setIsOpen(true)}
 *         placeholder="Select date"
 *       />
 *       {isOpen && dropdownPosition && (
 *         <Portal>
 *           <div
 *             style={{
 *               position: 'absolute',
 *               top: dropdownPosition.top,
 *               left: dropdownPosition.left,
 *             }}
 *           >
 *             <Calendar />
 *           </div>
 *         </Portal>
 *       )}
 *     </div>
 *   );
 * };
 * ```
 */
export function useDropdownPosition({
  isOpen,
  dropdownHeight = 240,
  gap = 4,
  viewportPadding = 8,
  matchWidth = true,
  customWidth = null,
  debounceDelay = 16,
}: UseDropdownPositionOptions): {
  dropdownPosition: DropdownPosition | null;
  containerRef: RefObject<HTMLDivElement | null>;
} {
  const [dropdownPosition, setDropdownPosition] =
    useState<DropdownPosition | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Calculate dropdown position with collision detection
  const updatePosition = useCallback(() => {
    if (containerRef.current && isOpen) {
      const rect = containerRef.current.getBoundingClientRect();

      // Calculate available space
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;

      // Determine if dropdown should flip above the input
      const shouldFlipUp =
        spaceBelow < dropdownHeight && spaceAbove > spaceBelow;

      // Calculate vertical position
      const top = shouldFlipUp
        ? rect.top + window.scrollY - dropdownHeight - gap
        : rect.bottom + window.scrollY + gap;

      // Calculate horizontal position with boundary constraints
      const targetWidth = matchWidth ? rect.width : customWidth;
      const dropdownWidth = targetWidth || rect.width;

      const left = Math.max(
        viewportPadding,
        Math.min(
          rect.left + window.scrollX,
          window.innerWidth - dropdownWidth - viewportPadding
        )
      );

      setDropdownPosition({
        top,
        left,
        width: matchWidth ? rect.width : customWidth,
        flipped: shouldFlipUp,
      });
    }
  }, [isOpen, dropdownHeight, gap, viewportPadding, matchWidth, customWidth]);

  // Memoize debounced position updater
  const debouncedUpdatePosition = useMemo(
    () => debounce(updatePosition, debounceDelay),
    [updatePosition, debounceDelay]
  );

  // Position calculation with debouncing for scroll/resize
  useEffect(() => {
    if (isOpen) {
      updatePosition(); // Immediate calculation on open
      window.addEventListener("scroll", debouncedUpdatePosition, true);
      window.addEventListener("resize", debouncedUpdatePosition);

      return () => {
        debouncedUpdatePosition.cancel();
        window.removeEventListener("scroll", debouncedUpdatePosition, true);
        window.removeEventListener("resize", debouncedUpdatePosition);
      };
    }
  }, [isOpen, updatePosition, debouncedUpdatePosition]);

  return { dropdownPosition, containerRef };
}
