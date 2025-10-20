"use client";

import { useEscape } from "@/hooks/useKeyPress";
import { createContext, useContext, useState, ReactNode } from "react";

export enum ModalIds {
  AgentsModal = "AgentsModal",
  CreateProjectModal = "CreateProjectModal",
  FeedbackModal = "FeedbackModal",
  AddInstructionModal = "AddInstructionModal",
  ProjectFilesModal = "ProjectFilesModal",
}

interface ModalProviderProps {
  children: ReactNode;
}

export function ChatModalProvider({ children }: ModalProviderProps) {
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
    <ChatModalContext.Provider value={{ isOpen, toggleModal, getModalData }}>
      {children}
    </ChatModalContext.Provider>
  );
}

interface ChatModalContextType {
  isOpen: (id: ModalIds) => boolean;
  toggleModal: (id: ModalIds, open: boolean, data?: any) => void;
  getModalData: <T = any>() => T | undefined;
}

const ChatModalContext = createContext<ChatModalContextType | undefined>(
  undefined
);

export function useChatModal() {
  const context = useContext(ChatModalContext);
  if (context === undefined) {
    throw new Error("useChatModal must be used within a ChatModalProvider");
  }
  return context;
}
