import { FiCheck } from "react-icons/fi";
import { Modal } from "@/components/Modal";
import { BasicClickable } from "@/components/BasicClickable";

export const GenericConfirmModal = ({
  title,
  message,
  confirmText = "Confirm",
  onClose,
  onConfirm,
}: {
  title: string;
  message: string;
  confirmText?: string;
  onClose: () => void;
  onConfirm: () => void;
}) => {
  return (
    <Modal onOutsideClick={onClose}>
      <div className="max-w-full">
        <div className="flex mb-4">
          <h2 className="my-auto text-2xl font-bold whitespace-normal overflow-wrap-normal">
            {title}
          </h2>
        </div>
        <p className="mb-4 whitespace-normal overflow-wrap-normal">{message}</p>
        <div className="flex">
          <div className="mx-auto">
            <BasicClickable onClick={onConfirm}>
              <div className="flex mx-2 items-center">
                <FiCheck className="mr-2 flex-shrink-0" />
                <span className="whitespace-normal overflow-wrap-normal">
                  {confirmText}
                </span>
              </div>
            </BasicClickable>
          </div>
        </div>
      </div>
    </Modal>
  );
};
