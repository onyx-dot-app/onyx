"use client";

import React, { createContext, useContext, useState, useCallback } from "react";

const ModalContext = createContext<ModalInterface | null>(null);

export interface ProviderProps {
  children?: React.ReactNode;
}

export interface ModalCreationInterface {
  isOpen: boolean;
  toggle: (state: boolean) => void;
  Provider: React.FunctionComponent<ProviderProps>;
}

export function useCreateModal(): ModalCreationInterface {
  const [isOpen, setIsOpen] = useState(false);

  const toggle = useCallback(
    (state: boolean) => {
      setIsOpen(state);
    },
    [setIsOpen]
  );

  const Provider: React.FunctionComponent<ProviderProps> = useCallback(
    ({ children }: ProviderProps) => {
      if (!isOpen) return null;

      return (
        <ModalContext.Provider value={{ isOpen, toggle }}>
          {children}
        </ModalContext.Provider>
      );
    },
    [isOpen, toggle]
  );

  return { isOpen, toggle, Provider };
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

export function useModalClose(onClose?: () => void): (() => void) | undefined {
  const context = useContext(ModalContext);

  return context
    ? () => {
        context.toggle(false);
        onClose?.();
      }
    : onClose;
}
