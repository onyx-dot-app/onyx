import { ModalType, ModalState } from "../hooks/useModal";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { UserSettingsModal } from "../modal/UserSettingsModal";
import { FilePickerModal } from "../my-documents/components/FilePicker";
import { ChatSearchModal } from "../chat_search/ChatSearchModal";
import { ShareChatSessionModal } from "../modal/ShareChatSessionModal";
import AssistantModal from "../../assistants/mine/AssistantModal";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { FeedbackModal } from "../modal/FeedbackModal";

interface ModalRendererProps {
  state: ModalState;
  onClose: () => void;
}

export function ModalRenderer({ state, onClose }: ModalRendererProps) {
  if (!state.isVisible) return null;

  switch (state.type) {
    case ModalType.API_KEY:
      const apiKeyData = state.data?.apiKey;
      if (!apiKeyData?.setPopup) return null;
      return <ApiKeyModal hide={onClose} setPopup={apiKeyData.setPopup} />;

    case ModalType.USER_SETTINGS:
    case ModalType.SETTINGS:
      const settingsData = state.data?.settings;
      if (
        !settingsData?.setPopup ||
        !settingsData?.setCurrentLlm ||
        !settingsData?.defaultModel ||
        !settingsData?.llmProviders
      )
        return null;
      return (
        <UserSettingsModal
          setPopup={settingsData.setPopup}
          setCurrentLlm={settingsData.setCurrentLlm}
          defaultModel={settingsData.defaultModel}
          llmProviders={settingsData.llmProviders}
          onClose={onClose}
        />
      );

    case ModalType.DOC_SELECTION:
      const docSelectionData = state.data?.docSelection;
      if (
        !docSelectionData?.setPresentingDocument ||
        !docSelectionData?.buttonContent ||
        !docSelectionData?.onSave
      )
        return null;
      return (
        <FilePickerModal
          setPresentingDocument={docSelectionData.setPresentingDocument}
          buttonContent={docSelectionData.buttonContent}
          isOpen={true}
          onClose={onClose}
          onSave={docSelectionData.onSave}
        />
      );

    case ModalType.CHAT_SEARCH:
      return <ChatSearchModal open={true} onCloseModal={onClose} />;

    case ModalType.SHARING:
      const sharingData = state.data?.sharing;
      if (
        !sharingData?.message ||
        !sharingData?.modelOverride ||
        !sharingData?.chatSessionId ||
        !sharingData?.existingSharedStatus
      )
        return null;
      return (
        <ShareChatSessionModal
          assistantId={sharingData.assistantId}
          message={sharingData.message}
          modelOverride={sharingData.modelOverride}
          chatSessionId={sharingData.chatSessionId}
          existingSharedStatus={sharingData.existingSharedStatus}
          onClose={onClose}
          onShare={sharingData.onShare}
        />
      );

    case ModalType.ASSISTANTS:
      return <AssistantModal hideModal={onClose} />;

    case ModalType.STACK_TRACE:
      const stackTraceData = state.data?.stackTrace;
      if (!stackTraceData?.exceptionTrace) return null;
      return (
        <ExceptionTraceModal
          onOutsideClick={onClose}
          exceptionTrace={stackTraceData.exceptionTrace}
        />
      );

    case ModalType.FEEDBACK:
      const feedbackData = state.data?.feedback;
      if (!feedbackData?.feedbackType || !feedbackData?.onSubmit) return null;
      return (
        <FeedbackModal
          feedbackType={feedbackData.feedbackType}
          onClose={onClose}
          onSubmit={feedbackData.onSubmit}
        />
      );

    case ModalType.SHARED_CHAT:
      const sharedChatData = state.data?.sharedChat;
      if (
        !sharedChatData?.message ||
        !sharedChatData?.modelOverride ||
        !sharedChatData?.chatSessionId ||
        !sharedChatData?.existingSharedStatus ||
        !sharedChatData?.onShare
      )
        return null;
      return (
        <ShareChatSessionModal
          assistantId={sharedChatData.assistantId}
          message={sharedChatData.message}
          modelOverride={sharedChatData.modelOverride}
          chatSessionId={sharedChatData.chatSessionId}
          existingSharedStatus={sharedChatData.existingSharedStatus}
          onClose={onClose}
          onShare={sharedChatData.onShare}
        />
      );

    default:
      return null;
  }
}
