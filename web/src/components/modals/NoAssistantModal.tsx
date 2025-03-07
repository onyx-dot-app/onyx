import { Modal } from "@/components/Modal";

export const NoAssistantModal = ({ isAdmin }: { isAdmin: boolean }) => {
  return (
    <Modal width="bg-white max-w-2xl rounded-lg shadow-xl text-center">
      <>
        <h2 className="text-3xl font-bold text-text-800 mb-4">
          No Assistant Available
        </h2>
        <p className="text-text-600 mb-6">
          You currently have no assistant configured. To use this feature, you
          need to take action.
        </p>
        {isAdmin ? (
          <>
            <p className="text-text-600 mb-6">
              As an administrator, you can create a new assistant by visiting
              the admin panel.
            </p>
            <button
              onClick={() => {
                window.location.href = "/admin/assistants";
              }}
              className="inline-flex flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-background-800 text-center focus:outline-none focus:ring-2 focus:ring-offset-2 "
            >
              Go to Admin Panel
            </button>
          </>
        ) : (
          <p className="text-text-600 mb-2">
            Please contact your administrator to configure an assistant for you.
          </p>
        )}
      </>
    </Modal>
  );
};
