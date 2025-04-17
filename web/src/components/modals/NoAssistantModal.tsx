import i18n from "@/i18n/init";
import k from "./../../i18n/keys";
import { Modal } from "@/components/Modal";

export const NoAssistantModal = ({ isAdmin }: { isAdmin: boolean }) => {
  return (
    <Modal width="bg-white max-w-2xl rounded-lg shadow-xl text-center">
      <>
        <h2 className="text-3xl font-bold text-text-800 mb-4">
          {i18n.t(k.NO_ASSISTANT_AVAILABLE)}
        </h2>
        <p className="text-text-600 mb-6">
          {i18n.t(k.YOU_CURRENTLY_HAVE_NO_ASSISTAN)}
        </p>
        {isAdmin ? (
          <>
            <p className="text-text-600 mb-6">
              {i18n.t(k.AS_AN_ADMINISTRATOR_YOU_CAN_C)}
            </p>
            <button
              onClick={() => {
                window.location.href = i18n.t(k.ADMIN_ASSISTANTS);
              }}
              className="inline-flex flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-background-800 text-center focus:outline-none focus:ring-2 focus:ring-offset-2 "
            >
              {i18n.t(k.GO_TO_ADMIN_PANEL)}
            </button>
          </>
        ) : (
          <p className="text-text-600 mb-2">
            {i18n.t(k.PLEASE_CONTACT_YOUR_ADMINISTRA)}
          </p>
        )}
      </>
    </Modal>
  );
};
