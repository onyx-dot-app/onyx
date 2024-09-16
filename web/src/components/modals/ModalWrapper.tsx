"use client";
import { XIcon } from "@/components/icons/icons";
import { isEventWithinRef } from "@/lib/contains";
import { useRef } from "react";

export const ModalWrapper = ({
  children,
  bgClassName,
  modalClassName,
  onClose,
}: {
  children: JSX.Element;
  bgClassName?: string;
  modalClassName?: string;
  onClose?: () => void;
}) => {
  const modalRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (
      onClose &&
      modalRef.current &&
      !modalRef.current.contains(e.target as Node) &&
      !isEventWithinRef(e.nativeEvent, modalRef)
    ) {
      onClose();
    }
  };
  return (
    <div
      onMouseDown={handleMouseDown}
      className={`fixed inset-0 bg-black bg-opacity-25 backdrop-blur-sm 
        flex items-center justify-center z-50 transition-opacity duration-300 ease-in-out
        ${bgClassName || ""}`}
    >
      <div
        ref={modalRef}
        onClick={(e) => {
          if (onClose) {
            e.stopPropagation();
          }
        }}
        className={`bg-background text-emphasis p-10 rounded shadow-2xl 
          w-11/12 max-w-3xl transform transition-all duration-300 ease-in-out
          relative ${modalClassName || ""}`}
      >
        {onClose && (
          <div className="absolute top-2 right-2">
            <button
              onClick={onClose}
              className="cursor-pointer text-text-500 hover:text-text-700 transition-colors duration-200 p-2"
              aria-label="Close modal"
            >
              <XIcon className="w-5 h-5" />
            </button>
          </div>
        )}

        <div className="flex w-full flex-col justify-stretch">{children}</div>
      </div>
    </div>
  );
};
