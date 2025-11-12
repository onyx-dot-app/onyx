"use client";

import React, { createContext, useContext, useState, useCallback } from "react";
import CoreModal, {
  CoreModalProps,
} from "@/refresh-components/modals/CoreModal";

const ModalContext = createContext<Modal | null>(null);

export interface ModalProvider {
  isOpen: boolean;
  toggle: (state: boolean) => void;
  Provider: React.FunctionComponent<CoreModalProps>;
}

export function useModalProvider(): ModalProvider {
  const [isOpen, setIsOpen] = useState(false);

  const toggle = useCallback((state: boolean) => {
    setIsOpen(state);
  }, []);

  const Provider: React.FunctionComponent<CoreModalProps> = useCallback(
    (props: CoreModalProps) => {
      if (!isOpen) return null;

      return (
        <ModalContext.Provider value={{ isOpen, toggle }}>
          <CoreModal {...props} />
        </ModalContext.Provider>
      );
    },
    [isOpen, toggle]
  );

  return { isOpen, toggle, Provider };
}

export interface Modal {
  isOpen: boolean;
  toggle: (state: boolean) => void;
}

export function useModal(): Modal {
  const context = useContext(ModalContext);

  if (!context) {
    throw new Error(
      "useModal must be used within a Modal created by createModalProvider"
    );
  }

  return context;
}
