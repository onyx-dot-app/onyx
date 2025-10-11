"use client";

import React, { createContext, useContext, useState, useCallback } from "react";
import CoreModal, {
  CoreModalProps,
} from "@/refresh-components/modals/CoreModal";

type ModalProps = Omit<CoreModalProps, "onClickOutside">;

interface UseModalProviderReturn {
  isOpen: boolean;
  toggle: (state: boolean) => void;
}

interface CreateModalProviderReturn {
  isOpen: boolean;
  toggle: (state: boolean) => void;
  ModalProvider: React.FunctionComponent<ModalProps>;
}

const ModalContext = createContext<UseModalProviderReturn | null>(null);

export function useModalProvider(): CreateModalProviderReturn {
  const [isOpen, setIsOpen] = useState(false);

  const toggle = useCallback((state: boolean) => {
    setIsOpen(state);
  }, []);

  const onClose = useCallback(() => {
    setIsOpen(false);
  }, []);

  const ModalProvider: React.FunctionComponent<ModalProps> = useCallback(
    (props: ModalProps) => {
      if (!isOpen) return null;

      return (
        <ModalContext.Provider value={{ isOpen, toggle }}>
          <CoreModal {...props} onClickOutside={onClose} />
        </ModalContext.Provider>
      );
    },
    [isOpen, toggle, onClose]
  );

  return { isOpen, toggle, ModalProvider };
}

export function useModal(): UseModalProviderReturn {
  const context = useContext(ModalContext);

  if (!context) {
    throw new Error(
      "useModal must be used within a Modal created by createModalProvider"
    );
  }

  return context;
}
