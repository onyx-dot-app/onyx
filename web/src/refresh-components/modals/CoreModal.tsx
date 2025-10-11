import React, { useEffect } from "react";
import ReactDOM from "react-dom";
import { MODAL_ROOT_ID } from "@/lib/constants";
import { cn } from "@/lib/utils";

const sizeClasses = {
  medium: "w-[64rem] h-[80dvh]",
  small: "w-[30rem]",
} as const;

export interface CoreModalProps {
  medium?: boolean;
  small?: boolean;

  onClickOutside?: () => void;
  className?: string;
  children?: React.ReactNode;
}

export default function CoreModal({
  medium,
  small,

  onClickOutside,
  className,
  children,
}: CoreModalProps) {
  const insideModal = React.useRef(false);
  const modalRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Focus the modal on mount for accessibility
    if (modalRef.current) {
      modalRef.current.focus();
    }
  }, []);

  // This must always exist.
  const modalRoot = document.getElementById(MODAL_ROOT_ID);
  if (!modalRoot)
    throw new Error(
      `A root div wrapping all children with the id ${MODAL_ROOT_ID} must exist, but was not found. This is an error. Go to "web/src/app/layout.tsx" and add a wrapper div with that id around the {children} invocation`
    );

  const size = medium ? "medium" : small ? "small" : "small";

  const modalContent = (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-mask-03 backdrop-blur-xl"
      onClick={() => (insideModal.current ? undefined : onClickOutside?.())}
    >
      <div
        ref={modalRef}
        className={cn(
          "z-10 rounded-16 flex border shadow-2xl flex-col bg-background-tint-00",
          sizeClasses[size],
          className
        )}
        onMouseOver={() => (insideModal.current = true)}
        onMouseEnter={() => (insideModal.current = true)}
        onMouseLeave={() => (insideModal.current = false)}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>
  );

  return ReactDOM.createPortal(
    modalContent,
    document.getElementById(MODAL_ROOT_ID)!
  );
}
