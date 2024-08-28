import { FiTrash, FiX } from "react-icons/fi";
import { ModalWrapper } from "@/components/modals/ModalWrapper";
import { BasicClickable } from "@/components/BasicClickable";

export const DeleteChatModal = ({
  chatSessionName,
  onClose,
  onSubmit,
}: {
  chatSessionName: string;
  onClose: () => void;
  onSubmit: () => void;
}) => {
  return (
    <ModalWrapper onClose={onClose}>
      <>
        <div className="flex mb-4">
          <h2 className="my-auto text-2xl font-bold">Delete chat?</h2>
        </div>
        <p className="mb-4">
          Click below to confirm that you want to delete{" "}
          <b>&quot;{chatSessionName.slice(0, 30)}&quot;</b>
        </p>
        <div className="flex">
          <div className="mx-auto">
            <BasicClickable onClick={onSubmit}>
              <div className="flex mx-2">
                <FiTrash className="my-auto mr-2" />
                Delete
              </div>
            </BasicClickable>
          </div>
        </div>
      </>
    </ModalWrapper>
  );
};
