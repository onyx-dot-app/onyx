import React from "react";
import ReactDOM from "react-dom";
import { MODAL_ROOT_ID } from "@/lib/constants";

interface CoreModalProps {
  onClickOutside?: () => void;
  className?: string;
  children?: React.ReactNode;
}

export default function CoreModal({
  onClickOutside,
  className,
  children,
}: CoreModalProps) {
  const insideModal = React.useRef(false);

  // This must always exist.
  const modalRoot = document.getElementById(MODAL_ROOT_ID);
  if (!modalRoot)
    throw new Error(
      `A root div wrapping all children with the id ${MODAL_ROOT_ID} must exist, but was not found. This is an error. Go to "web/src/app/layout.tsx" and add a wrapper div with that id around the {children} invocation`
    );

  const modalContent = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-mask-03 backdrop-blur-md"
      onClick={() => (insideModal.current ? undefined : onClickOutside?.())}
    >
      <div
        className={`z-10 rounded-16 border flex flex-col bg-background-tint-01 ${className}`}
        onMouseOver={() => (insideModal.current = true)}
        onMouseEnter={() => (insideModal.current = true)}
        onMouseLeave={() => (insideModal.current = false)}
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
