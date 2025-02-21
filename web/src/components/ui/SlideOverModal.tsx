import React, { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

const SlideOverModal = ({
  children,
  isOpen,
  onOpenChange,
  anchor,
}: {
  children: React.ReactNode;
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  anchor: React.RefObject<HTMLDivElement>;
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  useEffect(() => {
    if (isOpen && anchor?.current && modalRef.current) {
      const anchorRect = anchor.current.getBoundingClientRect();
      const modalRect = modalRef.current.getBoundingClientRect();

      const left = anchorRect.right + 10; // 10px to the right of the anchor
      const top = anchorRect.top + anchorRect.height / 2 - modalRect.height / 2;

      // Ensure the modal doesn't go off-screen vertically
      const adjustedTop = Math.max(
        10,
        Math.min(top, window.innerHeight - modalRect.height - 10)
      );

      modalRef.current.style.left = `${left}px`;
      modalRef.current.style.top = `${adjustedTop}px`;
    }
  }, [isOpen, anchor]);

  if (!isOpen || !mounted) return null;

  const modalContent = (
    <div className="fixed inset-0 overflow-hidden z-50">
      <div className="absolute inset-0 overflow-hidden">
        {/* Overlay */}
        <div
          className="absolute inset-0 bg-neutral-500 bg-opacity-75 transition-opacity"
          onClick={() => onOpenChange(false)}
        ></div>

        <div ref={modalRef} className="absolute">
          <div className="pointer-events-auto w-screen max-w-md">
            <div className="flex flex-col overflow-y-auto bg-white shadow-xl rounded-lg max-h-[80vh]">
              <div className="px-4 pt-6 sm:px-6">
                <div className="flex items-start justify-end">
                  <button
                    type="button"
                    className="rounded-md bg-white text-neutral-400 hover:text-neutral-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
                    onClick={() => onOpenChange(false)}
                  >
                    <span className="sr-only">Close panel</span>
                    <svg
                      className="h-6 w-6"
                      fill="none"
                      viewBox="0 0 24 24"
                      strokeWidth="1.5"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="relative flex-1 px-4 sm:px-6">{children}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
};

export default SlideOverModal;
