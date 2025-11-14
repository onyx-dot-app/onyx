"use client";

import React, { createContext, useContext, useState, useCallback } from "react";
import SimpleModal, {
  SimpleModalProps,
} from "@/refresh-components/SimpleModal";

type ModalProps = Omit<SimpleModalProps, "onClose">;

export const ModalContext = createContext<ModalInterface | null>(null);

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
          <SimpleModal {...props} onClose={() => toggle(false)} />
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
