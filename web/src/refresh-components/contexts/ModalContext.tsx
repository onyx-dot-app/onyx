"use client";

import React, { createContext, useContext, useState, useCallback } from "react";

interface ToggleHandler {
  isOpen: boolean;
  toggle: (state: boolean) => void;
}

interface CreateModalProviderReturn<P> extends ToggleHandler {
  Modal: React.FunctionComponent<P>;
}

const ModalContext = createContext<ToggleHandler | null>(null);

export function createModalProvider<P>(
  ModalComponent: React.FunctionComponent<P & { onClose: () => void }>
): CreateModalProviderReturn<P> {
  const [isOpen, setIsOpen] = useState(false);

  const toggle = useCallback((state: boolean) => {
    setIsOpen(state);
  }, []);

  const onClose = useCallback(() => {
    setIsOpen(false);
  }, []);

  const Modal: React.FunctionComponent<P> = useCallback(
    (props: P) => {
      if (!isOpen) return null;

      return (
        <ModalContext.Provider value={{ isOpen, toggle }}>
          <ModalComponent {...props} onClose={onClose} />
        </ModalContext.Provider>
      );
    },
    [isOpen, toggle, onClose]
  );

  return { isOpen, toggle, Modal };
}

export function useModal(): ToggleHandler {
  const context = useContext(ModalContext);

  if (!context) {
    throw new Error(
      "useModal must be used within a Modal created by createModalProvider"
    );
  }

  return context;
}
