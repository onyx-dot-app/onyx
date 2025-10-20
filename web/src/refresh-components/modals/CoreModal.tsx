import React from "react";
import ReactDOM from "react-dom";
import { MODAL_ROOT_ID } from "@/lib/constants";
import { cn } from "@/lib/utils";

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
  const modalRef = React.useRef<HTMLDivElement>(null);

  // Focus this `CoreModal` component when it mounts.
  // This is important, becaues it causes open popovers or things of the sort to CLOSE automatically (this is desired behaviour).
  // The current `Popover` will always close when another DOM node is focused on!
  React.useEffect(() => {
    if (!modalRef.current) return;
    modalRef.current.focus();
  }, []);

  // This must always exist.
  const modalRoot = document.getElementById(MODAL_ROOT_ID);
  if (!modalRoot)
    throw new Error(
      `A root div wrapping all children with the id ${MODAL_ROOT_ID} must exist, but was not found. This is an error. Go to "web/src/app/layout.tsx" and add a wrapper div with that id around the {children} invocation`
    );

  const modalContent = (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-mask-03 backdrop-blur-xl"
      onClick={() => (insideModal.current ? undefined : onClickOutside?.())}
    >
      <div
        ref={modalRef}
        className={cn(
          "z-10 rounded-16 flex border shadow-2xl flex-col bg-background-tint-00",
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
