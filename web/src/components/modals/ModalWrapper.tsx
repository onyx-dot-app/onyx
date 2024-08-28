"use client";
import { XIcon } from "@/components/icons/icons";
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
      !modalRef.current.contains(e.target as Node)
    ) {
      onClose();
    }
  };

  return (
    <div
      onMouseDown={handleMouseDown}
      className={
        "fixed inset-0 bg-black bg-opacity-30 backdrop-blur-sm " +
        "flex items-center justify-center z-50 " +
        (bgClassName || "")
      }
    >
      <div
        ref={modalRef}
        onClick={(e) => {
          if (onClose) {
            e.stopPropagation();
          }
        }}
        className={
          "bg-background text-emphasis p-8 rounded shadow-xl w-3/4 max-w-3xl shadow " +
          (modalClassName || "")
        }
      >
        {onClose && (
          <div className="w-full cursor-pointer flex justify-end">
            <button onClick={onClose}>
              <XIcon />
            </button>
          </div>
        )}

        {children}
      </div>
    </div>
  );
};
