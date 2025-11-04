import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  RefObject,
} from "react";
import { ComboBoxOption } from "./types";

function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): T & { cancel: () => void } {
  let timeout: NodeJS.Timeout | null = null;

  const debounced = function (this: any, ...args: Parameters<T>) {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  } as T & { cancel: () => void };

  debounced.cancel = () => {
    if (timeout) clearTimeout(timeout);
  };

  return debounced;
}

// =============================================================================
// HOOK: useComboBoxState
// =============================================================================

interface UseComboBoxStateProps {
  value: string;
  options: ComboBoxOption[];
}

/**
 * Manages the internal state of the ComboBox component
 * Handles state synchronization between external value prop and internal input state
 */
export function useComboBoxState({ value, options }: UseComboBoxStateProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);

  // State synchronization logic
  // Only sync when the dropdown is closed or when value changes significantly
  useEffect(() => {
    // If dropdown is closed, always sync with prop value
    if (!isOpen) {
      setInputValue(value);
    } else {
      // If dropdown is open, only sync if the new value is an exact match with an option
      // This prevents interference when user is typing
      const isExactOptionMatch = options.some((opt) => opt.value === value);
      if (isExactOptionMatch && inputValue !== value) {
        setInputValue(value);
      }
    }
  }, [value, isOpen, options, inputValue]);

  // Reset highlight and keyboard nav when closing dropdown
  useEffect(() => {
    if (!isOpen) {
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
    }
  }, [isOpen]);

  return {
    isOpen,
    setIsOpen,
    inputValue,
    setInputValue,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
  };
}

// =============================================================================
// HOOK: useDropdownPosition
// =============================================================================

interface DropdownPosition {
  top: number;
  left: number;
  width: number;
  flipped: boolean;
}

interface UseDropdownPositionProps {
  isOpen: boolean;
}

/**
 * Manages dropdown positioning with collision detection
 * Handles scroll and resize events with debouncing for performance
 */
export function useDropdownPosition({ isOpen }: UseDropdownPositionProps) {
  const [dropdownPosition, setDropdownPosition] =
    useState<DropdownPosition | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Calculate dropdown position with collision detection
  const updatePosition = useCallback(() => {
    if (containerRef.current && isOpen) {
      const rect = containerRef.current.getBoundingClientRect();
      const dropdownHeight = 240; // max-h-60 = 15rem = 240px
      const gap = 4; // margin between input and dropdown
      const viewportPadding = 8; // minimum distance from viewport edge

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
      const left = Math.max(
        viewportPadding,
        Math.min(
          rect.left + window.scrollX,
          window.innerWidth - rect.width - viewportPadding
        )
      );

      setDropdownPosition({
        top,
        left,
        width: rect.width,
        flipped: shouldFlipUp,
      });
    }
  }, [isOpen]);

  // Memoize debounced position updater
  const debouncedUpdatePosition = useMemo(
    () => debounce(updatePosition, 16), // ~60fps
    [updatePosition]
  );

  // Position calculation with debouncing for scroll/resize
  useEffect(() => {
    if (isOpen) {
      updatePosition(); // Immediate on open
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

// =============================================================================
// HOOK: useComboBoxKeyboard
// =============================================================================

interface UseComboBoxKeyboardProps {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  highlightedIndex: number;
  setHighlightedIndex: (index: number | ((prev: number) => number)) => void;
  setIsKeyboardNav: (isKeyboard: boolean) => void;
  allVisibleOptions: ComboBoxOption[];
  onSelect: (option: ComboBoxOption) => void;
  hasOptions: boolean;
}

/**
 * Manages keyboard navigation for the ComboBox
 * Handles arrow keys, Enter, Escape, and Tab
 */
export function useComboBoxKeyboard({
  isOpen,
  setIsOpen,
  highlightedIndex,
  setHighlightedIndex,
  setIsKeyboardNav,
  allVisibleOptions,
  onSelect,
  hasOptions,
}: UseComboBoxKeyboardProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (!hasOptions) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setIsKeyboardNav(true); // Mark as keyboard navigation
          if (!isOpen) {
            setIsOpen(true);
            setHighlightedIndex(0);
          } else {
            setHighlightedIndex((prev) => {
              // If no item highlighted yet (-1), start at 0
              if (prev === -1) return 0;
              // Otherwise move down if not at end
              return prev < allVisibleOptions.length - 1 ? prev + 1 : prev;
            });
          }
          break;
        case "ArrowUp":
          e.preventDefault();
          setIsKeyboardNav(true); // Mark as keyboard navigation
          if (isOpen) {
            setHighlightedIndex((prev) => {
              // If at first item or no highlight, don't go further up
              if (prev <= 0) return -1;
              return prev - 1;
            });
          }
          break;
        case "Enter":
          e.preventDefault();
          if (isOpen && highlightedIndex >= 0) {
            const option = allVisibleOptions[highlightedIndex];
            if (option) {
              onSelect(option);
            }
          }
          break;
        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
        case "Tab":
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
      }
    },
    [
      hasOptions,
      isOpen,
      allVisibleOptions,
      highlightedIndex,
      onSelect,
      setIsOpen,
      setHighlightedIndex,
      setIsKeyboardNav,
    ]
  );

  return { handleKeyDown };
}

// =============================================================================
// HOOK: useOptionFiltering
// =============================================================================

interface UseOptionFilteringProps {
  options: ComboBoxOption[];
  inputValue: string;
}

interface FilterResult {
  matchedOptions: ComboBoxOption[];
  unmatchedOptions: ComboBoxOption[];
  hasSearchTerm: boolean;
}

/**
 * Filters options based on input value
 * Splits options into matched and unmatched for better UX
 */
export function useOptionFiltering({
  options,
  inputValue,
}: UseOptionFilteringProps): FilterResult {
  return useMemo(() => {
    if (!options.length) {
      return { matchedOptions: [], unmatchedOptions: [], hasSearchTerm: false };
    }

    if (!inputValue || !inputValue.trim()) {
      return {
        matchedOptions: options,
        unmatchedOptions: [],
        hasSearchTerm: false,
      };
    }

    const searchTerm = inputValue.toLowerCase().trim();
    const matched: ComboBoxOption[] = [];
    const unmatched: ComboBoxOption[] = [];

    options.forEach((option) => {
      const matchesLabel = option.label.toLowerCase().includes(searchTerm);
      const matchesValue = option.value.toLowerCase().includes(searchTerm);

      if (matchesLabel || matchesValue) {
        matched.push(option);
      } else {
        unmatched.push(option);
      }
    });

    return {
      matchedOptions: matched,
      unmatchedOptions: unmatched,
      hasSearchTerm: true,
    };
  }, [options, inputValue]);
}

// =============================================================================
// HOOK: useClickOutside
// =============================================================================

interface UseClickOutsideProps {
  isOpen: boolean;
  refs: RefObject<HTMLElement>[];
  onClickOutside: () => void;
}

/**
 * Handles click-outside behavior to close dropdown
 * Listens for mousedown events outside specified refs
 */
export function useClickOutside({
  isOpen,
  refs,
  onClickOutside,
}: UseClickOutsideProps) {
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      // Check if click is outside all provided refs
      const isOutside = refs.every(
        (ref) => !ref.current || !ref.current.contains(event.target as Node)
      );

      if (isOutside) {
        onClickOutside();
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [isOpen, refs, onClickOutside]);
}
