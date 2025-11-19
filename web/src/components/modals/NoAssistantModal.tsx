import { Modal } from "@/components/Modal";
import Button from "@/refresh-components/buttons/Button";

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
            <Button
              className="w-full"
              onClick={() => {
                window.location.href = "/admin/assistants";
              }}
            >
              Go to Admin Panel
            </Button>
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
