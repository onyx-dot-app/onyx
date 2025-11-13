"use client";

import React, { createContext, useContext, useState, useCallback } from "react";
import ReactDOM from "react-dom";
import { MODAL_ROOT_ID } from "@/lib/constants";
import { cn, noProp } from "@/lib/utils";

interface ModalProps {
  className?: string;
  children?: React.ReactNode;
  onClose?: () => void;
}

function Modal({ className, children, onClose }: ModalProps) {
  const mouseDownOutside = React.useRef(false);
  const modalRef = React.useRef<HTMLDivElement>(null);

  // Focus this `CoreModal` component when it mounts.
  // This is important, becaues it causes open popovers or things of the sort to CLOSE automatically (this is desired behaviour).
  // The current `Popover` will always close when another DOM node is focused on!
  React.useEffect(() => {
    if (!modalRef.current) return;
    modalRef.current.focus();
  }, []);

  const modal = useModal();

  // This must always exist.
  const modalRoot = document.getElementById(MODAL_ROOT_ID);
  if (!modalRoot)
    throw new Error(
      `A root div wrapping all children with the id ${MODAL_ROOT_ID} must exist, but was not found. This is an error. Go to "web/src/app/layout.tsx" and add a wrapper div with that id around the {children} invocation`
    );

  const modalContent = (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-mask-03 backdrop-blur-03"
      onMouseDown={() => (mouseDownOutside.current = true)}
      onClick={() => {
        if (mouseDownOutside.current) {
          onClose?.();
          modal.toggle(false);
        }
        mouseDownOutside.current = false;
      }}
    >
      <div
        ref={modalRef}
        className={cn(
          "z-10 rounded-16 flex border shadow-2xl flex-col bg-background-tint-00 overflow-hidden",
          className
        )}
        onMouseDown={noProp(() => {
          mouseDownOutside.current = false;
        })}
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

const ModalContext = createContext<ModalInterface | null>(null);

export interface ModalCreationInterface {
  isOpen: boolean;
  toggle: (state: boolean) => void;
  Modal: React.FunctionComponent<ModalProps>;
}

export function useCreateModal(): ModalCreationInterface {
  const [isOpen, setIsOpen] = useState(false);

  const toggle = useCallback(
    (state: boolean) => {
      setIsOpen(state);
    },
    [setIsOpen]
  );

  const ModalWrapper: React.FunctionComponent<ModalProps> = useCallback(
    (props: ModalProps) => {
      if (!isOpen) return null;

      return (
        <ModalContext.Provider value={{ isOpen, toggle }}>
          <Modal {...props} />
        </ModalContext.Provider>
      );
    },
    [isOpen, toggle]
  );

  return { isOpen, toggle, Modal: ModalWrapper };
}

export interface ModalInterface {
  isOpen: boolean;
  toggle: (state: boolean) => void;
}

export function useModal(): ModalInterface {
  const context = useContext(ModalContext);

  if (!context) {
    throw new Error(
      "useModal must be used within the `Modal` field returned by `useCreateModal`"
    );
  }

  return context;
}
