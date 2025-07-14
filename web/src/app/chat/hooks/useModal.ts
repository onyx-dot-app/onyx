import { useReducer, useMemo } from "react";
import { FeedbackType } from "../types";

// Modal Types Enum
export enum ModalType {
  NONE = "NONE",
  API_KEY = "API_KEY",
  USER_SETTINGS = "USER_SETTINGS",
  SETTINGS = "SETTINGS",
  DOC_SELECTION = "DOC_SELECTION",
  CHAT_SEARCH = "CHAT_SEARCH",
  SHARING = "SHARING",
  ASSISTANTS = "ASSISTANTS",
  STACK_TRACE = "STACK_TRACE",
  FEEDBACK = "FEEDBACK",
  SHARED_CHAT = "SHARED_CHAT",
}

// Modal Data Types
// Ideally most state & data doesn't need to be passed via action, but to start we're only extracting
// the modal visibility/ shared state logic, keeping the messy state management logic that already exists
interface ModalData {
  // API Key Modal
  apiKey?: {
    hide: () => void;
    setPopup: (popup: any) => void;
  };

  // Settings Modals
  settings?: {
    setPopup: (popup: any) => void;
    setCurrentLlm: (llm: any) => void;
    defaultModel: string;
    llmProviders: any[];
    onClose: () => void;
  };

  // Document Selection Modal
  docSelection?: {
    setPresentingDocument: (doc: any) => void;
    buttonContent: string;
    onClose: () => void;
    onSave: () => void;
  };

  // Chat Search Modal
  chatSearch?: {
    onCloseModal: () => void;
  };

  // Sharing Modal
  sharing?: {
    assistantId?: number;
    message: string;
    modelOverride: any;
    chatSessionId: string;
    existingSharedStatus: any;
    onClose: () => void;
    onShare?: (shared: boolean) => void;
  };

  // Assistants Modal
  assistants?: {
    hideModal: () => void;
  };

  // Stack Trace Modal
  stackTrace?: {
    exceptionTrace: string;
    onOutsideClick: () => void;
  };

  // Feedback Modal
  feedback?: {
    feedbackType: FeedbackType;
    messageId: number;
    onClose: () => void;
    onSubmit: (data: any) => void;
  };

  // Shared Chat Modal
  sharedChat?: {
    assistantId?: number;
    message: string;
    modelOverride: any;
    chatSessionId: string;
    existingSharedStatus: any;
    onClose: () => void;
    onShare: (shared: boolean) => void;
  };
}

// Modal State Interface
interface ModalState {
  isVisible: boolean;
  type: ModalType;
  data?: ModalData;
}

// Modal Actions
type ModalAction =
  | { type: "MODAL_OPEN"; payload: { type: ModalType; data?: ModalData } }
  | { type: "MODAL_CLOSE" }
  | { type: "MODAL_UPDATE_DATA"; payload: Partial<ModalData> };

// Modal Reducer
const modalReducer = (state: ModalState, action: ModalAction): ModalState => {
  switch (action.type) {
    case "MODAL_OPEN":
      return {
        isVisible: true,
        type: action.payload.type,
        data: action.payload.data,
      };

    case "MODAL_CLOSE":
      return {
        isVisible: false,
        type: ModalType.NONE,
        data: undefined,
      };

    case "MODAL_UPDATE_DATA":
      return {
        ...state,
        data: { ...state.data, ...action.payload },
      };

    default:
      return state;
  }
};

// Modal Hook with Convenience Methods
export function useModal() {
  const [state, dispatch] = useReducer(modalReducer, {
    isVisible: false,
    type: ModalType.NONE,
    data: undefined,
  });

  const modalActions = useMemo(
    () => ({
      // Generic actions
      openModal: (type: ModalType, data?: ModalData) =>
        dispatch({ type: "MODAL_OPEN", payload: { type, data } }),
      closeModal: () => dispatch({ type: "MODAL_CLOSE" }),
      updateModalData: (data: Partial<ModalData>) =>
        dispatch({ type: "MODAL_UPDATE_DATA", payload: data }),

      // Convenience methods for each modal type
      openApiKeyModal: (data: ModalData["apiKey"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.API_KEY, data: { apiKey: data } },
        }),

      openUserSettingsModal: (data: ModalData["settings"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.USER_SETTINGS, data: { settings: data } },
        }),

      openSettingsModal: (data: ModalData["settings"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.SETTINGS, data: { settings: data } },
        }),

      openDocSelectionModal: (data: ModalData["docSelection"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: {
            type: ModalType.DOC_SELECTION,
            data: { docSelection: data },
          },
        }),

      openChatSearchModal: (data: ModalData["chatSearch"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.CHAT_SEARCH, data: { chatSearch: data } },
        }),

      openSharingModal: (data: ModalData["sharing"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.SHARING, data: { sharing: data } },
        }),

      openAssistantsModal: (data: ModalData["assistants"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.ASSISTANTS, data: { assistants: data } },
        }),

      openStackTraceModal: (data: ModalData["stackTrace"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.STACK_TRACE, data: { stackTrace: data } },
        }),

      openFeedbackModal: (data: ModalData["feedback"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.FEEDBACK, data: { feedback: data } },
        }),

      openSharedChatModal: (data: ModalData["sharedChat"]) =>
        dispatch({
          type: "MODAL_OPEN",
          payload: { type: ModalType.SHARED_CHAT, data: { sharedChat: data } },
        }),
    }),
    [dispatch]
  );

  return { state, actions: modalActions };
}

export type { ModalState, ModalData };
