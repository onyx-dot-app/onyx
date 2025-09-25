"use client";

import { useEscape } from "@/hooks/useEscape";
import { createContext, useContext, useState, ReactNode } from "react";

export enum ModalIds {
  AgentsModal = "AgentsModal",
  UserSettingsModal = "UserSettingsModal",
}

interface ModalProviderProps {
  children: ReactNode;
}

export function ModalProvider({ children }: ModalProviderProps) {
  const [openModal, setOpenModal] = useState<string | undefined>();

  function toggleModal(id: ModalIds, open: boolean) {
    if (openModal !== undefined) {
      if (openModal === id && !open) setOpenModal(undefined);
      else if (openModal !== id && open) setOpenModal(id);
    } else {
      if (open) setOpenModal(id);
    }
  }

  function isOpen(id: string): boolean {
    return openModal === id;
  }

  useEscape(() => setOpenModal(undefined));

  return (
    <ModalContext.Provider value={{ isOpen, toggleModal }}>
      {children}
    </ModalContext.Provider>
  );
}

interface ModalContextType {
  isOpen: (id: ModalIds) => boolean;
  toggleModal: (id: ModalIds, open: boolean) => void;
}

const ModalContext = createContext<ModalContextType | undefined>(undefined);

export function useModal() {
  const context = useContext(ModalContext);
  if (context === undefined) {
    throw new Error("useModal must be used within a ModalProvider");
  }
  return context;
}
