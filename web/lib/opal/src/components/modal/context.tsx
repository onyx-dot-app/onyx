"use client";

import React, { createContext, useContext, useState, useCallback } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ModalProviderProps {
  children?: React.ReactNode;
}

interface ModalInterface {
  isOpen: boolean;
  toggle: (state: boolean) => void;
}

interface ModalCreationInterface extends ModalInterface {
  /** Mounts children only while open, with the modal state in context. */
  Provider: React.FunctionComponent<ModalProviderProps>;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ModalContext = createContext<ModalInterface | null>(null);

/**
 * Owns one modal's open state. Render modal content inside the returned
 * `Provider`: it mounts children only while open, and descendants reach the
 * state via `useModal` / `useModalClose` without prop drilling.
 */
function useCreateModal(): ModalCreationInterface {
  const [isOpen, setIsOpen] = useState(false);

  const toggle = useCallback((state: boolean) => {
    setIsOpen(state);
  }, []);

  const Provider: React.FunctionComponent<ModalProviderProps> = useCallback(
    ({ children }: ModalProviderProps) => {
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

/** Modal state from the nearest `useCreateModal` Provider. Throws outside one. */
function useModal(): ModalInterface {
  const context = useContext(ModalContext);

  if (!context) {
    throw new Error(
      "useModal must be used within the `Provider` returned by `useCreateModal`"
    );
  }

  return context;
}

/**
 * Close-and-callback: closes the nearest modal then runs `onClose`. Outside
 * a Provider it returns `onClose` as-is, so components work in both places.
 */
function useModalClose(onClose?: () => void): (() => void) | undefined {
  const context = useContext(ModalContext);

  return context
    ? () => {
        context.toggle(false);
        onClose?.();
      }
    : onClose;
}

export {
  useCreateModal,
  useModal,
  useModalClose,
  type ModalInterface,
  type ModalCreationInterface,
  type ModalProviderProps,
};
