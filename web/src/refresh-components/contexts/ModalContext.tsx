"use client";

import { useEscape } from "@/hooks/useKeyPress";
import { createContext, useContext, useState, ReactNode } from "react";

export enum ModalIds {
  AgentsModal = "AgentsModal",
  UserSettingsModal = "UserSettingsModal",
  CreateProjectModal = "CreateProjectModal",
  FeedbackModal = "FeedbackModal",
}

interface ModalProviderProps {
  children: ReactNode;
}

export function ModalProvider({ children }: ModalProviderProps) {
  const [openModal, setOpenModal] = useState<string | undefined>();
  const [modalData, setModalData] = useState<any | undefined>();

  function toggleModal(id: ModalIds, open: boolean, data?: any) {
    if (openModal !== undefined) {
      if (openModal === id && !open) {
        setOpenModal(undefined);
        setModalData(undefined);
      } else if (openModal !== id && open) {
        setOpenModal(id);
        setModalData(data);
      }
    } else {
      if (open) {
        setOpenModal(id);
        setModalData(data);
      }
    }
  }

  function isOpen(id: string): boolean {
    return openModal === id;
  }

  function getModalData<T = any>(): T | undefined {
    return modalData as T | undefined;
  }

  useEscape(() => {
    setOpenModal(undefined);
    setModalData(undefined);
  });

  return (
    <ModalContext.Provider value={{ isOpen, toggleModal, getModalData }}>
      {children}
    </ModalContext.Provider>
  );
}

interface ModalContextType {
  isOpen: (id: ModalIds) => boolean;
  toggleModal: (id: ModalIds, open: boolean, data?: any) => void;
  getModalData: <T = any>() => T | undefined;
}

const ModalContext = createContext<ModalContextType | undefined>(undefined);

export function useModal() {
  const context = useContext(ModalContext);
  if (context === undefined) {
    throw new Error("useModal must be used within a ModalProvider");
  }
  return context;
}
