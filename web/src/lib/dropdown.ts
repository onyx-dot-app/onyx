import { RefObject, useCallback, useEffect } from "react";

interface DropdownPositionProps {
  isOpen: boolean;
  dropdownRef: RefObject<HTMLElement>;
  dropdownMenuRef: RefObject<HTMLElement>;
}

// This hook manages the positioning of a dropdown menu relative to its trigger element.
// It ensures the menu is positioned correctly, adjusting for viewport boundaries and scroll position.
// Also adds event listeners for window resize and scroll to update the position dynamically.
export const useDropdownPosition = ({
  isOpen,
  dropdownRef,
  dropdownMenuRef,
}: DropdownPositionProps) => {
  const updateMenuPosition = useCallback(() => {
    if (isOpen && dropdownRef.current && dropdownMenuRef.current) {
      const rect = dropdownRef.current.getBoundingClientRect();
      const menuRect = dropdownMenuRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const viewportWidth = window.innerWidth;

      let top = rect.bottom + window.scrollY;
      let left = rect.left + window.scrollX;

      // Check if there's enough space below
      if (rect.bottom + menuRect.height <= viewportHeight) {
        // Position below the trigger
        top = rect.bottom + window.scrollY;
      } else if (rect.top - menuRect.height >= 0) {
        // Position above the trigger if there's not enough space below
        top = rect.top + window.scrollY - menuRect.height;
      } else {
        // If there's not enough space above or below, position at the bottom of the viewport
        top = viewportHeight + window.scrollY - menuRect.height;
      }

      // Ensure the dropdown doesn't go off the right edge of the screen
      if (left + menuRect.width > viewportWidth) {
        left = viewportWidth - menuRect.width + window.scrollX;
      }

      dropdownMenuRef.current.style.position = "absolute";
      dropdownMenuRef.current.style.top = `${top}px`;
      dropdownMenuRef.current.style.left = `${rect.left + window.scrollX}px`;
      dropdownMenuRef.current.style.width = `${rect.width}px`;
      dropdownMenuRef.current.style.zIndex = "10000";
    }
  }, [isOpen, dropdownRef, dropdownMenuRef]);

  useEffect(() => {
    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition);

    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition);
    };
  }, [isOpen, updateMenuPosition]);

  return updateMenuPosition;
};
