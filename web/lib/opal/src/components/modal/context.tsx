"use client";

import React, {
  createContext,
  useContext,
  useCallback,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

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
  /** True while open, and while the modal animates out after closing. */
  isPresent: boolean;
  /**
   * Mounts children while the modal is present, with the modal state in
   * context. Children unmount once the modal has animated out, so the next
   * open starts with fresh state.
   */
  Provider: React.FunctionComponent<ModalProviderProps>;
}

/** What `Modal` reads from its owner to animate out before it unmounts. */
interface ModalOwner extends ModalInterface {
  onExitComplete: () => void;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface ModalState {
  isOpen: boolean;
  isPresent: boolean;
}

const CLOSED: ModalState = { isOpen: false, isPresent: false };

// The state lives outside React so `Provider` keeps one identity. A new
// identity would remount the children as the modal closes and skip its
// exit animation.
function createModalStore() {
  let state = CLOSED;
  const listeners = new Set<() => void>();
  const set = (next: ModalState) => {
    if (next.isOpen === state.isOpen && next.isPresent === state.isPresent) {
      return;
    }
    state = next;
    listeners.forEach((listener) => listener());
  };
  return {
    get: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    toggle: (open: boolean) =>
      set(
        open
          ? { isOpen: true, isPresent: true }
          : { isOpen: false, isPresent: state.isPresent }
      ),
    // Ignored while open: a nested modal closing must not unmount its owner.
    onExitComplete: () => {
      if (!state.isOpen) set(CLOSED);
    },
  };
}

type ModalStore = ReturnType<typeof createModalStore>;

function useModalState(store: ModalStore): ModalState {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ModalContext = createContext<ModalOwner | null>(null);

/**
 * Owns one modal's open state. Render modal content inside the returned
 * `Provider`: it mounts children while the modal is present, and
 * descendants reach the state via `useModal` / `useModalClose` without prop
 * drilling.
 */
function useCreateModal(): ModalCreationInterface {
  const [store] = useState(createModalStore);
  const { isOpen, isPresent } = useModalState(store);

  const Provider = useMemo(() => {
    function ModalOwnerProvider({ children }: ModalProviderProps) {
      const state = useModalState(store);
      const value = useMemo<ModalOwner>(
        () => ({
          isOpen: state.isOpen,
          toggle: store.toggle,
          onExitComplete: store.onExitComplete,
        }),
        [state.isOpen]
      );
      if (!state.isPresent) return null;
      return (
        <ModalContext.Provider value={value}>{children}</ModalContext.Provider>
      );
    }
    return ModalOwnerProvider;
  }, [store]);

  return { isOpen, isPresent, toggle: store.toggle, Provider };
}

/** The nearest `useCreateModal` owner, or null outside one. */
function useModalOwner(): ModalOwner | null {
  return useContext(ModalContext);
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
  const toggle = context?.toggle;

  const close = useCallback(() => {
    toggle?.(false);
    onClose?.();
  }, [toggle, onClose]);

  return toggle ? close : onClose;
}

export {
  useCreateModal,
  useModal,
  useModalClose,
  useModalOwner,
  type ModalInterface,
  type ModalCreationInterface,
  type ModalProviderProps,
};
